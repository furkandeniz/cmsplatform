import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.database import SessionLocal
from app.email_notify import BASE_URL, parse_recipients, send_alert_email
from app.health_check import run_health_check
from app.lighthouse_check import run_lighthouse_check
from app.models import CronJob, Environment, Scenario
from app.scenario_runner import run_scenario
from app.seo_check import run_seo_check
from app.ssl_check import run_ssl_check

logger = logging.getLogger("cmsplus.scheduler")

CHECK_TYPE_LABELS = {
    "health": "Sağlık Kontrolü",
    "ssl": "SSL Kontrolü",
    "seo": "SEO Kontrolü",
    "lighthouse": "Lighthouse",
    "scenario": "Senaryo",
}

CHECK_RUNNERS = {
    "health": run_health_check,
    "ssl": run_ssl_check,
    "seo": run_seo_check,
    "lighthouse": run_lighthouse_check,
}

CHECK_OK_ATTR = {
    "health": "last_check_ok",
    "ssl": "ssl_ok",
    "seo": "last_seo_ok",
    "lighthouse": "last_lighthouse_ok",
}

CHECK_ERROR_ATTR = {
    "health": "last_check_error",
    "ssl": "ssl_error",
    "seo": "last_seo_error",
    "lighthouse": "last_lighthouse_error",
}

FREQUENCY_LABELS = {
    "15m": "Her 15 dakika",
    "1h": "Saatlik",
    "6h": "Her 6 saatte bir",
    "24h": "Günlük",
    "7d": "Haftalık",
}

FREQUENCY_INTERVALS = {
    "15m": {"minutes": 15},
    "1h": {"hours": 1},
    "6h": {"hours": 6},
    "24h": {"hours": 24},
    "7d": {"days": 7},
}

scheduler = BackgroundScheduler(timezone="UTC")


def _job_id(cron_job_id: int) -> str:
    return f"cron-job-{cron_job_id}"


def _notify_state_change(cron_job: CronJob, environment: Environment, project_name: str, current_ok: bool) -> None:
    if not cron_job.notify_enabled:
        return
    recipients = parse_recipients(cron_job.notify_emails or "")
    if not recipients:
        return

    if cron_job.check_type == "scenario" and cron_job.scenario:
        label = f"Senaryo: {cron_job.scenario.name}"
    else:
        label = CHECK_TYPE_LABELS.get(cron_job.check_type, cron_job.check_type)
    env_url = f"{BASE_URL}/projects/{environment.project_id}/environments/{environment.id}"

    if current_ok:
        subject = f"[CMSPlus] {environment.name} ({project_name}) · {label} normale döndü"
        body = (
            f"{project_name} projesi, {environment.name} ortamı için {label} tekrar başarılı.\n\n"
            f"Ortam URL: {environment.url}\n"
            f"Detay: {env_url}\n"
        )
    else:
        error_message = (
            cron_job.last_run_error
            if cron_job.check_type == "scenario"
            else getattr(environment, CHECK_ERROR_ATTR[cron_job.check_type], None)
        )
        subject = f"[CMSPlus] {environment.name} ({project_name}) · {label} başarısız"
        body = (
            f"{project_name} projesi, {environment.name} ortamı için {label} başarısız oldu.\n\n"
            f"Ortam URL: {environment.url}\n"
            f"Hata: {error_message or 'Bilinmiyor'}\n"
            f"Detay: {env_url}\n"
        )
    send_alert_email(recipients, subject, body)


def _execute_cron_job(cron_job_id: int) -> None:
    with SessionLocal() as db:
        cron_job = db.get(CronJob, cron_job_id)
        if cron_job is None or not cron_job.is_active:
            return
        environment = db.get(Environment, cron_job.environment_id)
        if environment is None:
            return
        is_scenario = cron_job.check_type == "scenario"
        runner = None if is_scenario else CHECK_RUNNERS.get(cron_job.check_type)
        if not is_scenario and runner is None:
            return

        previous_ok = cron_job.last_run_ok
        project_name = environment.project.name
        current_ok: Optional[bool] = None

        try:
            if is_scenario:
                scenario = db.get(Scenario, cron_job.scenario_id) if cron_job.scenario_id else None
                if scenario is None:
                    raise RuntimeError("Senaryo bulunamadı (silinmiş olabilir)")
                run = run_scenario(scenario)
                current_ok = run.ok
                cron_job.last_run_ok = current_ok
                cron_job.last_run_error = None if current_ok else (run.error or "Senaryo başarısız")
            else:
                runner(environment)
                current_ok = getattr(environment, CHECK_OK_ATTR[cron_job.check_type])
                cron_job.last_run_ok = current_ok
                cron_job.last_run_error = (
                    None if current_ok else getattr(environment, CHECK_ERROR_ATTR[cron_job.check_type], None)
                )
        except Exception as exc:
            current_ok = False
            cron_job.last_run_ok = False
            cron_job.last_run_error = str(exc)[:255]
            logger.exception("Cron job %s (%s) failed", cron_job_id, cron_job.check_type)
        cron_job.last_run_at = datetime.now(timezone.utc)
        db.commit()

        should_notify = (not current_ok) if previous_ok is None else (previous_ok != current_ok)
        if should_notify:
            _notify_state_change(cron_job, environment, project_name, bool(current_ok))


def schedule_job(cron_job: CronJob) -> None:
    interval = FREQUENCY_INTERVALS.get(cron_job.frequency)
    if interval is None:
        return
    scheduler.add_job(
        _execute_cron_job,
        trigger=IntervalTrigger(**interval),
        args=[cron_job.id],
        id=_job_id(cron_job.id),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


def unschedule_job(cron_job_id: int) -> None:
    try:
        scheduler.remove_job(_job_id(cron_job_id))
    except JobLookupError:
        pass


def get_next_run_time(cron_job_id: int) -> Optional[datetime]:
    job = scheduler.get_job(_job_id(cron_job_id))
    return job.next_run_time if job else None


def start_scheduler() -> None:
    if scheduler.running:
        return
    with SessionLocal() as db:
        active_jobs = db.scalars(select(CronJob).where(CronJob.is_active.is_(True))).all()
        for cron_job in active_jobs:
            schedule_job(cron_job)
    scheduler.start()
