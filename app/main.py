import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from starlette.status import HTTP_303_SEE_OTHER

from app.database import Base, engine, SessionLocal
from app.health_check import run_health_check as _run_health_check
from app.lighthouse_check import run_lighthouse_check
from app.models import (
    CronJob,
    Environment,
    EnvironmentComparison,
    HealthCheck,
    LighthouseCheck,
    Project,
    Scenario,
    ScenarioRun,
    ScenarioStep,
    SeoCheck,
)
from app.scenario_runner import OPERATOR_LABELS as SCENARIO_OPERATOR_LABELS
from app.scenario_runner import SCREENSHOT_DIR as SCENARIO_SCREENSHOT_DIR
from app.scenario_runner import STEP_TYPE_LABELS as SCENARIO_STEP_TYPE_LABELS
from app.scenario_runner import describe_step, run_scenario as execute_scenario
from app.scheduler import (
    CHECK_TYPE_LABELS,
    FREQUENCY_LABELS,
    get_next_run_time,
    schedule_job,
    start_scheduler,
    unschedule_job,
)
from app.seo_check import run_seo_check
from app.ssl_check import run_ssl_check as _run_ssl_check
from app.visual_compare import UPLOAD_DIR as COMPARISON_UPLOAD_DIR
from app.visual_compare import run_comparison

Base.metadata.create_all(bind=engine)

app = FastAPI(title="CMSPlus")


@app.on_event("startup")
def _start_scheduler_on_startup() -> None:
    start_scheduler()

STATIC_DIR = Path("app/static")
UPLOAD_DIR = STATIC_DIR / "uploads" / "logos"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["tojson_pretty"] = lambda value: json.dumps(
    value, indent=2, ensure_ascii=False, default=str
)
templates.env.filters["fromjson"] = lambda value: json.loads(value) if value else []


def static_asset_url(relative_path: str) -> str:
    """Appends the file's last-modified time as a cache-busting query param,
    so browsers always fetch the latest JS/CSS after a deploy without manual
    version bumps or stale-cache bugs."""
    try:
        version = int((STATIC_DIR / relative_path).stat().st_mtime)
    except OSError:
        version = 0
    return f"/static/{relative_path}?v={version}"


templates.env.globals["static_asset_url"] = static_asset_url

ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"}


def _save_logo(logo: Optional[UploadFile]) -> Optional[str]:
    if logo is None or not logo.filename:
        return None
    extension = Path(logo.filename).suffix.lower()
    if extension not in ALLOWED_LOGO_EXTENSIONS:
        return None
    filename = f"{uuid.uuid4().hex}{extension}"
    destination = UPLOAD_DIR / filename
    with destination.open("wb") as out_file:
        out_file.write(logo.file.read())
    return f"uploads/logos/{filename}"


def _delete_logo_file(logo_path: Optional[str]) -> None:
    if not logo_path:
        return
    file_path = STATIC_DIR / logo_path
    file_path.unlink(missing_ok=True)


def _get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Proje bulunamadı")
    return project


def _get_environment_or_404(db: Session, project_id: int, environment_id: int) -> Environment:
    environment = db.get(Environment, environment_id)
    if environment is None or environment.project_id != project_id:
        raise HTTPException(status_code=404, detail="Ortam bulunamadı")
    return environment


@app.get("/")
def welcome(request: Request):
    with SessionLocal() as db:
        projects = db.scalars(select(Project).order_by(Project.name)).all()
        return templates.TemplateResponse(
            request, "welcome.html", {"projects": projects}
        )


@app.get("/projects/new")
def new_project_form(request: Request):
    return templates.TemplateResponse(request, "project_form.html", {"project": None})


@app.post("/projects")
def create_project(
    name: str = Form(...),
    env_name: str = Form(...),
    env_url: str = Form(...),
    env_drupal_version: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    logo: Optional[UploadFile] = File(None),
):
    logo_path = _save_logo(logo)
    with SessionLocal() as db:
        project = Project(
            name=name.strip(),
            notes=(notes or "").strip() or None,
            logo_path=logo_path,
        )
        project.environments.append(
            Environment(
                name=env_name.strip(),
                url=env_url.strip(),
                drupal_version=(env_drupal_version or "").strip() or None,
                is_primary=True,
            )
        )
        db.add(project)
        db.commit()
        new_id = project.id
    return RedirectResponse(url=f"/projects/{new_id}", status_code=HTTP_303_SEE_OTHER)


@app.get("/projects/{project_id}")
def project_detail(project_id: int, request: Request):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        return templates.TemplateResponse(
            request, "project_detail.html", {"project": project}
        )


@app.get("/projects/{project_id}/edit")
def edit_project_form(project_id: int, request: Request):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        return templates.TemplateResponse(
            request, "project_form.html", {"project": project}
        )


@app.post("/projects/{project_id}/edit")
def update_project(
    project_id: int,
    name: str = Form(...),
    notes: Optional[str] = Form(None),
    logo: Optional[UploadFile] = File(None),
):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        new_logo_path = _save_logo(logo)
        if new_logo_path:
            _delete_logo_file(project.logo_path)
            project.logo_path = new_logo_path

        project.name = name.strip()
        project.notes = (notes or "").strip() or None
        db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/projects/{project_id}/delete")
def delete_project(project_id: int):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        _delete_logo_file(project.logo_path)
        db.delete(project)
        db.commit()
    return RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)


@app.get("/projects/{project_id}/environments/new")
def new_environment_form(project_id: int, request: Request):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        return templates.TemplateResponse(
            request, "environment_form.html", {"project": project, "environment": None}
        )


@app.get("/projects/{project_id}/environments/{environment_id}")
def environment_detail(project_id: int, environment_id: int, request: Request):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        environment = _get_environment_or_404(db, project_id, environment_id)
        cron_jobs_with_next_run = [
            (cron_job, get_next_run_time(cron_job.id)) for cron_job in environment.cron_jobs
        ]
        return templates.TemplateResponse(
            request,
            "environment_detail.html",
            {
                "project": project,
                "environment": environment,
                "cron_jobs_with_next_run": cron_jobs_with_next_run,
                "check_type_labels": CHECK_TYPE_LABELS,
                "frequency_labels": FREQUENCY_LABELS,
            },
        )


@app.post("/projects/{project_id}/environments")
def create_environment(
    project_id: int,
    name: str = Form(...),
    url: str = Form(...),
    drupal_version: Optional[str] = Form(None),
):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        is_first = len(project.environments) == 0
        environment = Environment(
            project_id=project.id,
            name=name.strip(),
            url=url.strip(),
            drupal_version=(drupal_version or "").strip() or None,
            is_primary=is_first,
        )
        db.add(environment)
        db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)


@app.get("/projects/{project_id}/environments/{environment_id}/edit")
def edit_environment_form(project_id: int, environment_id: int, request: Request):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        environment = _get_environment_or_404(db, project_id, environment_id)
        return templates.TemplateResponse(
            request,
            "environment_form.html",
            {"project": project, "environment": environment},
        )


@app.post("/projects/{project_id}/environments/{environment_id}/edit")
def update_environment(
    project_id: int,
    environment_id: int,
    name: str = Form(...),
    url: str = Form(...),
    drupal_version: Optional[str] = Form(None),
):
    with SessionLocal() as db:
        environment = _get_environment_or_404(db, project_id, environment_id)
        environment.name = name.strip()
        environment.url = url.strip()
        environment.drupal_version = (drupal_version or "").strip() or None
        db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/projects/{project_id}/environments/{environment_id}/delete")
def delete_environment(project_id: int, environment_id: int):
    with SessionLocal() as db:
        environment = _get_environment_or_404(db, project_id, environment_id)
        was_primary = environment.is_primary
        db.delete(environment)
        db.flush()
        if was_primary:
            next_environment = db.scalars(
                select(Environment)
                .where(Environment.project_id == project_id)
                .order_by(Environment.name)
                .limit(1)
            ).first()
            if next_environment:
                next_environment.is_primary = True
        db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/projects/{project_id}/environments/{environment_id}/check")
def check_environment(project_id: int, environment_id: int):
    with SessionLocal() as db:
        environment = _get_environment_or_404(db, project_id, environment_id)
        _run_health_check(environment)
        db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/projects/{project_id}/environments/{environment_id}/ssl-check")
def check_environment_ssl(project_id: int, environment_id: int):
    with SessionLocal() as db:
        environment = _get_environment_or_404(db, project_id, environment_id)
        _run_ssl_check(environment)
        db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/projects/{project_id}/environments/{environment_id}/seo-check")
def check_environment_seo(project_id: int, environment_id: int):
    with SessionLocal() as db:
        environment = _get_environment_or_404(db, project_id, environment_id)
        run_seo_check(environment)
        db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/projects/{project_id}/environments/{environment_id}/lighthouse-check")
def check_environment_lighthouse(project_id: int, environment_id: int):
    with SessionLocal() as db:
        environment = _get_environment_or_404(db, project_id, environment_id)
        run_lighthouse_check(environment)
        db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/projects/{project_id}/environments/{environment_id}/set-primary")
def set_primary_environment(project_id: int, environment_id: int):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        target = _get_environment_or_404(db, project_id, environment_id)
        for environment in project.environments:
            environment.is_primary = environment.id == target.id
        db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)


def _get_cron_job_or_404(db: Session, environment_id: int, cron_job_id: int) -> CronJob:
    cron_job = db.get(CronJob, cron_job_id)
    if cron_job is None or cron_job.environment_id != environment_id:
        raise HTTPException(status_code=404, detail="Cron job bulunamadı")
    return cron_job


@app.post("/projects/{project_id}/environments/{environment_id}/cron-jobs")
def create_cron_job(
    project_id: int,
    environment_id: int,
    check_type: str = Form(...),
    frequency: str = Form(...),
    notify_enabled: Optional[str] = Form(None),
    notify_emails: Optional[str] = Form(None),
):
    scenario_id: Optional[int] = None
    if check_type.startswith("scenario:"):
        scenario_id_part = check_type.split(":", 1)[1]
        if not scenario_id_part.isdigit():
            raise HTTPException(status_code=400, detail="Geçersiz senaryo")
        scenario_id = int(scenario_id_part)
        check_type = "scenario"
    if check_type not in CHECK_TYPE_LABELS or frequency not in FREQUENCY_LABELS:
        raise HTTPException(status_code=400, detail="Geçersiz kontrol türü veya sıklık")
    with SessionLocal() as db:
        _get_environment_or_404(db, project_id, environment_id)
        if check_type == "scenario":
            scenario = db.get(Scenario, scenario_id)
            if scenario is None or scenario.environment_id != environment_id:
                raise HTTPException(status_code=404, detail="Senaryo bulunamadı")
        query = select(CronJob).where(
            CronJob.environment_id == environment_id,
            CronJob.check_type == check_type,
        )
        if check_type == "scenario":
            query = query.where(CronJob.scenario_id == scenario_id)
        cron_job = db.scalars(query).first()
        if cron_job is None:
            cron_job = CronJob(
                environment_id=environment_id,
                check_type=check_type,
                scenario_id=scenario_id,
                frequency=frequency,
            )
            db.add(cron_job)
        else:
            cron_job.frequency = frequency
            cron_job.is_active = True
        cron_job.notify_enabled = bool(notify_enabled)
        cron_job.notify_emails = (notify_emails or "").strip() or None
        db.commit()
        db.refresh(cron_job)
        schedule_job(cron_job)
    return RedirectResponse(
        url=f"/projects/{project_id}/environments/{environment_id}", status_code=HTTP_303_SEE_OTHER
    )


@app.post("/projects/{project_id}/environments/{environment_id}/cron-jobs/{cron_job_id}/notify")
def update_cron_job_notifications(
    project_id: int,
    environment_id: int,
    cron_job_id: int,
    notify_enabled: Optional[str] = Form(None),
    notify_emails: Optional[str] = Form(None),
):
    with SessionLocal() as db:
        _get_environment_or_404(db, project_id, environment_id)
        cron_job = _get_cron_job_or_404(db, environment_id, cron_job_id)
        cron_job.notify_enabled = bool(notify_enabled)
        cron_job.notify_emails = (notify_emails or "").strip() or None
        db.commit()
    return RedirectResponse(
        url=f"/projects/{project_id}/environments/{environment_id}", status_code=HTTP_303_SEE_OTHER
    )


@app.post("/projects/{project_id}/environments/{environment_id}/cron-jobs/{cron_job_id}/toggle")
def toggle_cron_job(project_id: int, environment_id: int, cron_job_id: int):
    with SessionLocal() as db:
        _get_environment_or_404(db, project_id, environment_id)
        cron_job = _get_cron_job_or_404(db, environment_id, cron_job_id)
        cron_job.is_active = not cron_job.is_active
        db.commit()
        if cron_job.is_active:
            schedule_job(cron_job)
        else:
            unschedule_job(cron_job.id)
    return RedirectResponse(
        url=f"/projects/{project_id}/environments/{environment_id}", status_code=HTTP_303_SEE_OTHER
    )


@app.post("/projects/{project_id}/environments/{environment_id}/cron-jobs/{cron_job_id}/delete")
def delete_cron_job(project_id: int, environment_id: int, cron_job_id: int):
    with SessionLocal() as db:
        _get_environment_or_404(db, project_id, environment_id)
        cron_job = _get_cron_job_or_404(db, environment_id, cron_job_id)
        cron_job_id_value = cron_job.id
        db.delete(cron_job)
        db.commit()
    unschedule_job(cron_job_id_value)
    return RedirectResponse(
        url=f"/projects/{project_id}/environments/{environment_id}", status_code=HTTP_303_SEE_OTHER
    )


def _get_health_check_or_404(db: Session, check_id: int) -> HealthCheck:
    check = db.get(HealthCheck, check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="Kontrol kaydı bulunamadı")
    return check


def _health_check_to_dict(check: HealthCheck) -> dict:
    return {
        "id": check.id,
        "project": check.environment.project.name,
        "environment": check.environment.name,
        "url": check.environment.url,
        "checked_at": check.checked_at.isoformat(),
        "ok": check.ok,
        "status_code": check.status_code,
        "response_ms": check.response_ms,
        "error": check.error,
        "content_type": check.content_type,
        "response_headers": json.loads(check.response_headers) if check.response_headers else None,
        "response_body": check.response_body,
    }


HEALTH_CHECK_TIME_PRESETS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


@app.get("/health-checks")
def health_checks_list(
    request: Request,
    environment_id: Optional[int] = None,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    since: Optional[str] = None,
):
    with SessionLocal() as db:
        query = (
            select(HealthCheck)
            .options(joinedload(HealthCheck.environment).joinedload(Environment.project))
            .order_by(HealthCheck.checked_at.desc())
        )
        if environment_id is not None:
            query = query.where(HealthCheck.environment_id == environment_id)
        if project_id is not None:
            query = query.where(HealthCheck.environment.has(Environment.project_id == project_id))
        if status == "ok":
            query = query.where(HealthCheck.ok.is_(True))
        elif status == "fail":
            query = query.where(HealthCheck.ok.is_(False))
        if since in HEALTH_CHECK_TIME_PRESETS:
            cutoff = datetime.now(timezone.utc) - HEALTH_CHECK_TIME_PRESETS[since]
            query = query.where(HealthCheck.checked_at >= cutoff)

        checks = db.scalars(query.limit(200)).all()

        filtered_environment = None
        if environment_id is not None:
            filtered_environment = db.get(Environment, environment_id)

        projects = db.scalars(select(Project).order_by(Project.name)).all()

        non_environment_params = {
            key: value
            for key, value in {"project_id": project_id, "status": status, "since": since}.items()
            if value
        }
        clear_environment_url = "/health-checks"
        if non_environment_params:
            clear_environment_url += "?" + urlencode(non_environment_params)

        return templates.TemplateResponse(
            request,
            "health_checks.html",
            {
                "checks": checks,
                "filtered_environment": filtered_environment,
                "clear_environment_url": clear_environment_url,
                "projects": projects,
                "selected_project_id": project_id,
                "selected_status": status,
                "selected_since": since,
            },
        )


@app.get("/health-checks/{check_id}")
def health_check_detail(check_id: int, request: Request):
    with SessionLocal() as db:
        check = _get_health_check_or_404(db, check_id)
        return templates.TemplateResponse(
            request,
            "health_check_detail.html",
            {"check": check, "check_json": _health_check_to_dict(check)},
        )


@app.get("/health-checks/{check_id}/json")
def health_check_json(check_id: int):
    with SessionLocal() as db:
        check = _get_health_check_or_404(db, check_id)
        return JSONResponse(_health_check_to_dict(check))


def _get_seo_check_or_404(db: Session, check_id: int) -> SeoCheck:
    check = db.get(SeoCheck, check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="SEO kontrol kaydı bulunamadı")
    return check


def _seo_check_to_dict(check: SeoCheck) -> dict:
    return {
        "id": check.id,
        "project": check.environment.project.name,
        "environment": check.environment.name,
        "url": check.environment.url,
        "checked_at": check.checked_at.isoformat(),
        "ok": check.ok,
        "error": check.error,
        "status_code": check.status_code,
        "load_time_ms": check.load_time_ms,
        "score": check.score,
        "title": check.title,
        "meta_description": check.meta_description,
        "canonical_url": check.canonical_url,
        "meta_robots": check.meta_robots,
        "h1_count": check.h1_count,
        "h1_text": check.h1_text,
        "image_count": check.image_count,
        "images_missing_alt": check.images_missing_alt,
        "internal_link_count": check.internal_link_count,
        "external_link_count": check.external_link_count,
        "has_viewport": check.has_viewport,
        "lang": check.lang,
        "og_title": check.og_title,
        "og_description": check.og_description,
        "og_image": check.og_image,
        "has_structured_data": check.has_structured_data,
        "word_count": check.word_count,
        "issues": json.loads(check.issues) if check.issues else [],
    }


def _build_seo_report(checks: list) -> dict:
    """Aggregate SEO check history into a per-environment score/trend summary
    and a most-common-issues frequency table using pandas."""
    empty_report = {
        "avg_score": None,
        "total_checks": 0,
        "failed_checks": 0,
        "top_issues": [],
        "environment_summary": [],
    }
    if not checks:
        return empty_report

    records = [
        {
            "environment_id": check.environment_id,
            "environment_name": check.environment.name,
            "project_name": check.environment.project.name,
            "checked_at": check.checked_at,
            "ok": check.ok,
            "score": check.score,
            "issues": json.loads(check.issues) if check.issues else [],
        }
        for check in checks
    ]
    df = pd.DataFrame(records)

    total_checks = len(df)
    failed_checks = int((~df["ok"]).sum())
    ok_scores = df.loc[df["ok"], "score"]
    avg_score = round(ok_scores.mean(), 1) if not ok_scores.empty else None

    top_issues = []
    ok_issues = df.loc[df["ok"], "issues"]
    if not ok_issues.empty:
        exploded = ok_issues.explode().dropna()
        if not exploded.empty:
            counts = exploded.value_counts().head(8)
            top_issues = [
                {"issue": issue, "count": int(count)} for issue, count in counts.items()
            ]

    environment_summary = []
    for environment_id, group in df.sort_values("checked_at").groupby("environment_id"):
        group_ok = group[group["ok"]]
        latest = group.iloc[-1]
        latest_score = None
        trend = None
        if not group_ok.empty:
            latest_ok = group_ok.iloc[-1]
            latest_score = int(latest_ok["score"])
            if len(group_ok) >= 2:
                trend = int(latest_ok["score"] - group_ok.iloc[-2]["score"])
        environment_summary.append(
            {
                "environment_id": int(environment_id),
                "environment_name": latest["environment_name"],
                "project_name": latest["project_name"],
                "latest_score": latest_score,
                "trend": trend,
                "checked_at": latest["checked_at"],
                "check_count": len(group),
            }
        )

    environment_summary.sort(
        key=lambda item: (item["latest_score"] is None, item["latest_score"] if item["latest_score"] is not None else 0)
    )

    return {
        "avg_score": avg_score,
        "total_checks": total_checks,
        "failed_checks": failed_checks,
        "top_issues": top_issues,
        "environment_summary": environment_summary,
    }


@app.get("/seo-checks")
def seo_checks_list(
    request: Request,
    environment_id: Optional[int] = None,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    since: Optional[str] = None,
):
    with SessionLocal() as db:
        query = (
            select(SeoCheck)
            .options(joinedload(SeoCheck.environment).joinedload(Environment.project))
            .order_by(SeoCheck.checked_at.desc())
        )
        if environment_id is not None:
            query = query.where(SeoCheck.environment_id == environment_id)
        if project_id is not None:
            query = query.where(SeoCheck.environment.has(Environment.project_id == project_id))
        if status == "ok":
            query = query.where(SeoCheck.ok.is_(True))
        elif status == "fail":
            query = query.where(SeoCheck.ok.is_(False))
        if since in HEALTH_CHECK_TIME_PRESETS:
            cutoff = datetime.now(timezone.utc) - HEALTH_CHECK_TIME_PRESETS[since]
            query = query.where(SeoCheck.checked_at >= cutoff)

        checks = db.scalars(query.limit(500)).all()

        filtered_environment = None
        if environment_id is not None:
            filtered_environment = db.get(Environment, environment_id)

        projects = db.scalars(select(Project).order_by(Project.name)).all()

        non_environment_params = {
            key: value
            for key, value in {"project_id": project_id, "status": status, "since": since}.items()
            if value
        }
        clear_environment_url = "/seo-checks"
        if non_environment_params:
            clear_environment_url += "?" + urlencode(non_environment_params)

        report = _build_seo_report(checks)

        return templates.TemplateResponse(
            request,
            "seo_checks.html",
            {
                "checks": checks,
                "filtered_environment": filtered_environment,
                "clear_environment_url": clear_environment_url,
                "projects": projects,
                "selected_project_id": project_id,
                "selected_status": status,
                "selected_since": since,
                "report": report,
            },
        )


@app.get("/seo-checks/{check_id}")
def seo_check_detail(check_id: int, request: Request):
    with SessionLocal() as db:
        check = _get_seo_check_or_404(db, check_id)
        return templates.TemplateResponse(
            request,
            "seo_check_detail.html",
            {
                "check": check,
                "check_json": _seo_check_to_dict(check),
                "issues": json.loads(check.issues) if check.issues else [],
            },
        )


@app.get("/seo-checks/{check_id}/json")
def seo_check_json(check_id: int):
    with SessionLocal() as db:
        check = _get_seo_check_or_404(db, check_id)
        return JSONResponse(_seo_check_to_dict(check))


def _get_lighthouse_check_or_404(db: Session, check_id: int) -> LighthouseCheck:
    check = db.get(LighthouseCheck, check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="Lighthouse kontrol kaydı bulunamadı")
    return check


def _lighthouse_check_to_dict(check: LighthouseCheck) -> dict:
    return {
        "id": check.id,
        "project": check.environment.project.name,
        "environment": check.environment.name,
        "url": check.environment.url,
        "checked_at": check.checked_at.isoformat(),
        "ok": check.ok,
        "error": check.error,
        "duration_ms": check.duration_ms,
        "performance_score": check.performance_score,
        "accessibility_score": check.accessibility_score,
        "best_practices_score": check.best_practices_score,
        "seo_score": check.seo_score,
        "audits": json.loads(check.audits) if check.audits else [],
    }


LIGHTHOUSE_CATEGORY_COLUMNS = [
    ("performance_score", "performance"),
    ("accessibility_score", "accessibility"),
    ("best_practices_score", "best_practices"),
    ("seo_score", "seo"),
]


def _build_lighthouse_report(checks: list) -> dict:
    """Aggregate Lighthouse check history into per-environment score/trend summary
    and a most-common-failing-audit frequency table using pandas."""
    empty_report = {
        "avg_scores": {},
        "total_checks": 0,
        "failed_checks": 0,
        "top_audits": [],
        "environment_summary": [],
    }
    if not checks:
        return empty_report

    records = [
        {
            "environment_id": check.environment_id,
            "environment_name": check.environment.name,
            "project_name": check.environment.project.name,
            "checked_at": check.checked_at,
            "ok": check.ok,
            "performance_score": check.performance_score,
            "accessibility_score": check.accessibility_score,
            "best_practices_score": check.best_practices_score,
            "seo_score": check.seo_score,
            "audits": json.loads(check.audits) if check.audits else [],
        }
        for check in checks
    ]
    df = pd.DataFrame(records)

    total_checks = len(df)
    failed_checks = int((~df["ok"]).sum())
    df_ok = df[df["ok"]]

    avg_scores = {}
    for column, label in LIGHTHOUSE_CATEGORY_COLUMNS:
        series = df_ok[column].dropna()
        avg_scores[label] = round(series.mean(), 1) if not series.empty else None

    top_audits = []
    ok_audits = df_ok["audits"]
    if not ok_audits.empty:
        exploded = ok_audits.explode().dropna()
        if not exploded.empty:
            titles = exploded.apply(lambda item: item["title"])
            counts = titles.value_counts().head(8)
            top_audits = [{"title": title, "count": int(count)} for title, count in counts.items()]

    def overall_score(row) -> Optional[float]:
        values = [row[column] for column, _ in LIGHTHOUSE_CATEGORY_COLUMNS if pd.notna(row[column])]
        return sum(values) / len(values) if values else None

    environment_summary = []
    for environment_id, group in df.sort_values("checked_at").groupby("environment_id"):
        group_ok = group[group["ok"]]
        latest = group.iloc[-1]
        scores = {label: None for _, label in LIGHTHOUSE_CATEGORY_COLUMNS}
        trend = None
        if not group_ok.empty:
            latest_ok = group_ok.iloc[-1]
            scores = {
                label: (int(latest_ok[column]) if pd.notna(latest_ok[column]) else None)
                for column, label in LIGHTHOUSE_CATEGORY_COLUMNS
            }
            if len(group_ok) >= 2:
                previous_ok = group_ok.iloc[-2]
                latest_overall = overall_score(latest_ok)
                previous_overall = overall_score(previous_ok)
                if latest_overall is not None and previous_overall is not None:
                    trend = round(latest_overall - previous_overall, 1)
        environment_summary.append(
            {
                "environment_id": int(environment_id),
                "environment_name": latest["environment_name"],
                "project_name": latest["project_name"],
                "scores": scores,
                "trend": trend,
                "checked_at": latest["checked_at"],
            }
        )

    def sort_key(item):
        values = [v for v in item["scores"].values() if v is not None]
        avg = sum(values) / len(values) if values else None
        return (avg is None, avg if avg is not None else 0)

    environment_summary.sort(key=sort_key)

    return {
        "avg_scores": avg_scores,
        "total_checks": total_checks,
        "failed_checks": failed_checks,
        "top_audits": top_audits,
        "environment_summary": environment_summary,
    }


@app.get("/lighthouse-checks")
def lighthouse_checks_list(
    request: Request,
    environment_id: Optional[int] = None,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    since: Optional[str] = None,
):
    with SessionLocal() as db:
        query = (
            select(LighthouseCheck)
            .options(joinedload(LighthouseCheck.environment).joinedload(Environment.project))
            .order_by(LighthouseCheck.checked_at.desc())
        )
        if environment_id is not None:
            query = query.where(LighthouseCheck.environment_id == environment_id)
        if project_id is not None:
            query = query.where(LighthouseCheck.environment.has(Environment.project_id == project_id))
        if status == "ok":
            query = query.where(LighthouseCheck.ok.is_(True))
        elif status == "fail":
            query = query.where(LighthouseCheck.ok.is_(False))
        if since in HEALTH_CHECK_TIME_PRESETS:
            cutoff = datetime.now(timezone.utc) - HEALTH_CHECK_TIME_PRESETS[since]
            query = query.where(LighthouseCheck.checked_at >= cutoff)

        checks = db.scalars(query.limit(500)).all()

        filtered_environment = None
        if environment_id is not None:
            filtered_environment = db.get(Environment, environment_id)

        projects = db.scalars(select(Project).order_by(Project.name)).all()

        non_environment_params = {
            key: value
            for key, value in {"project_id": project_id, "status": status, "since": since}.items()
            if value
        }
        clear_environment_url = "/lighthouse-checks"
        if non_environment_params:
            clear_environment_url += "?" + urlencode(non_environment_params)

        report = _build_lighthouse_report(checks)

        return templates.TemplateResponse(
            request,
            "lighthouse_checks.html",
            {
                "checks": checks,
                "filtered_environment": filtered_environment,
                "clear_environment_url": clear_environment_url,
                "projects": projects,
                "selected_project_id": project_id,
                "selected_status": status,
                "selected_since": since,
                "report": report,
            },
        )


@app.get("/lighthouse-checks/{check_id}")
def lighthouse_check_detail(check_id: int, request: Request):
    with SessionLocal() as db:
        check = _get_lighthouse_check_or_404(db, check_id)
        return templates.TemplateResponse(
            request,
            "lighthouse_check_detail.html",
            {
                "check": check,
                "check_json": _lighthouse_check_to_dict(check),
                "audits": json.loads(check.audits) if check.audits else [],
            },
        )


@app.get("/lighthouse-checks/{check_id}/json")
def lighthouse_check_json(check_id: int):
    with SessionLocal() as db:
        check = _get_lighthouse_check_or_404(db, check_id)
        return JSONResponse(_lighthouse_check_to_dict(check))


@app.get("/projects/{project_id}/compare")
def compare_list(project_id: int, request: Request):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        comparisons = db.scalars(
            select(EnvironmentComparison)
            .where(EnvironmentComparison.project_id == project_id)
            .order_by(EnvironmentComparison.created_at.desc())
        ).all()
        return templates.TemplateResponse(
            request, "compare_list.html", {"project": project, "comparisons": comparisons}
        )


@app.get("/projects/{project_id}/compare/new")
def new_comparison_form(project_id: int, request: Request):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        if len(project.environments) < 2:
            raise HTTPException(status_code=400, detail="Karşılaştırma için en az 2 ortam gerekli")
        return templates.TemplateResponse(request, "compare_form.html", {"project": project})


@app.post("/projects/{project_id}/compare")
def create_comparison(
    project_id: int,
    environment_a_id: int = Form(...),
    environment_b_id: int = Form(...),
    paths: str = Form(...),
):
    if environment_a_id == environment_b_id:
        raise HTTPException(status_code=400, detail="Aynı ortamı kendisiyle karşılaştıramazsın")
    path_list = [p.strip() for p in paths.splitlines() if p.strip()]
    if not path_list:
        raise HTTPException(status_code=400, detail="En az bir sayfa yolu girmelisin")

    with SessionLocal() as db:
        _get_project_or_404(db, project_id)
        _get_environment_or_404(db, project_id, environment_a_id)
        _get_environment_or_404(db, project_id, environment_b_id)

        comparison = EnvironmentComparison(
            project_id=project_id,
            environment_a_id=environment_a_id,
            environment_b_id=environment_b_id,
        )
        db.add(comparison)
        db.commit()
        db.refresh(comparison)

        run_comparison(comparison, path_list)
        db.commit()
        comparison_id = comparison.id

    return RedirectResponse(
        url=f"/projects/{project_id}/compare/{comparison_id}", status_code=HTTP_303_SEE_OTHER
    )


@app.get("/projects/{project_id}/compare/{comparison_id}")
def comparison_detail(project_id: int, comparison_id: int, request: Request):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        comparison = db.get(EnvironmentComparison, comparison_id)
        if comparison is None or comparison.project_id != project_id:
            raise HTTPException(status_code=404, detail="Karşılaştırma bulunamadı")
        return templates.TemplateResponse(
            request, "compare_result.html", {"project": project, "comparison": comparison}
        )


@app.post("/projects/{project_id}/compare/{comparison_id}/delete")
def delete_comparison(project_id: int, comparison_id: int):
    with SessionLocal() as db:
        comparison = db.get(EnvironmentComparison, comparison_id)
        if comparison is None or comparison.project_id != project_id:
            raise HTTPException(status_code=404, detail="Karşılaştırma bulunamadı")
        db.delete(comparison)
        db.commit()
    shutil.rmtree(COMPARISON_UPLOAD_DIR / str(comparison_id), ignore_errors=True)
    return RedirectResponse(url=f"/projects/{project_id}/compare", status_code=HTTP_303_SEE_OTHER)


def _get_scenario_or_404(db: Session, environment_id: int, scenario_id: int) -> Scenario:
    scenario = db.get(Scenario, scenario_id)
    if scenario is None or scenario.environment_id != environment_id:
        raise HTTPException(status_code=404, detail="Senaryo bulunamadı")
    return scenario


def _get_scenario_step_or_404(db: Session, scenario_id: int, step_id: int) -> ScenarioStep:
    step = db.get(ScenarioStep, step_id)
    if step is None or step.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="Adım bulunamadı")
    return step


def _get_scenario_run_or_404(db: Session, scenario_id: int, run_id: int) -> ScenarioRun:
    run = db.get(ScenarioRun, run_id)
    if run is None or run.scenario_id != scenario_id:
        raise HTTPException(status_code=404, detail="Çalıştırma bulunamadı")
    return run


def _parse_optional_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


@app.post("/projects/{project_id}/environments/{environment_id}/scenarios")
def create_scenario(project_id: int, environment_id: int, name: str = Form(...)):
    with SessionLocal() as db:
        _get_environment_or_404(db, project_id, environment_id)
        scenario = Scenario(environment_id=environment_id, name=name.strip())
        db.add(scenario)
        db.commit()
        db.refresh(scenario)
        scenario_id = scenario.id
    return RedirectResponse(
        url=f"/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}",
        status_code=HTTP_303_SEE_OTHER,
    )


SCENARIO_RUNS_PAGE_SIZE = 10


@app.get("/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}")
def scenario_detail(
    project_id: int,
    environment_id: int,
    scenario_id: int,
    request: Request,
    page: int = 1,
):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        environment = _get_environment_or_404(db, project_id, environment_id)
        scenario = _get_scenario_or_404(db, environment_id, scenario_id)
        steps_with_description = [(step, describe_step(step)) for step in scenario.steps]

        total_runs = db.scalar(
            select(func.count())
            .select_from(ScenarioRun)
            .where(ScenarioRun.scenario_id == scenario_id)
        )
        total_pages = ceil(total_runs / SCENARIO_RUNS_PAGE_SIZE) if total_runs else 1
        page = min(max(page, 1), total_pages)
        runs = db.scalars(
            select(ScenarioRun)
            .where(ScenarioRun.scenario_id == scenario_id)
            .order_by(ScenarioRun.run_at.desc())
            .offset((page - 1) * SCENARIO_RUNS_PAGE_SIZE)
            .limit(SCENARIO_RUNS_PAGE_SIZE)
        ).all()

        return templates.TemplateResponse(
            request,
            "scenario_detail.html",
            {
                "project": project,
                "environment": environment,
                "scenario": scenario,
                "steps_with_description": steps_with_description,
                "step_type_labels": SCENARIO_STEP_TYPE_LABELS,
                "operator_labels": SCENARIO_OPERATOR_LABELS,
                "runs": runs,
                "runs_page": page,
                "runs_total_pages": total_pages,
                "runs_total": total_runs,
            },
        )


@app.post("/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}/steps")
def add_scenario_step(
    project_id: int,
    environment_id: int,
    scenario_id: int,
    step_type: str = Form(...),
    path: Optional[str] = Form(None),
    selector: Optional[str] = Form(None),
    value: Optional[str] = Form(None),
    value2: Optional[str] = Form(None),
    operator: Optional[str] = Form(None),
    count: Optional[str] = Form(None),
    wait_ms: Optional[str] = Form(None),
):
    if step_type not in SCENARIO_STEP_TYPE_LABELS:
        raise HTTPException(status_code=400, detail="Geçersiz adım türü")
    with SessionLocal() as db:
        scenario = _get_scenario_or_404(db, environment_id, scenario_id)
        next_position = max((step.position for step in scenario.steps), default=-1) + 1
        step = ScenarioStep(
            scenario_id=scenario_id,
            position=next_position,
            step_type=step_type,
            path=(path or "").strip() or None,
            selector=(selector or "").strip() or None,
            value=(value or "").strip() or None,
            value2=(value2 or "").strip() or None,
            operator=(operator or "").strip() or None,
            count=_parse_optional_int(count),
            wait_ms=_parse_optional_int(wait_ms),
        )
        db.add(step)
        db.commit()
    return RedirectResponse(
        url=f"/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}",
        status_code=HTTP_303_SEE_OTHER,
    )


@app.post(
    "/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}/steps/{step_id}/delete"
)
def delete_scenario_step(project_id: int, environment_id: int, scenario_id: int, step_id: int):
    with SessionLocal() as db:
        _get_scenario_or_404(db, environment_id, scenario_id)
        step = _get_scenario_step_or_404(db, scenario_id, step_id)
        db.delete(step)
        db.commit()
    return RedirectResponse(
        url=f"/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}",
        status_code=HTTP_303_SEE_OTHER,
    )


@app.post(
    "/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}/steps/{step_id}/edit"
)
def edit_scenario_step(
    project_id: int,
    environment_id: int,
    scenario_id: int,
    step_id: int,
    step_type: str = Form(...),
    path: Optional[str] = Form(None),
    selector: Optional[str] = Form(None),
    value: Optional[str] = Form(None),
    value2: Optional[str] = Form(None),
    operator: Optional[str] = Form(None),
    count: Optional[str] = Form(None),
    wait_ms: Optional[str] = Form(None),
):
    if step_type not in SCENARIO_STEP_TYPE_LABELS:
        raise HTTPException(status_code=400, detail="Geçersiz adım türü")
    with SessionLocal() as db:
        _get_scenario_or_404(db, environment_id, scenario_id)
        step = _get_scenario_step_or_404(db, scenario_id, step_id)
        step.step_type = step_type
        step.path = (path or "").strip() or None
        step.selector = (selector or "").strip() or None
        step.value = (value or "").strip() or None
        step.value2 = (value2 or "").strip() or None
        step.operator = (operator or "").strip() or None
        step.count = _parse_optional_int(count)
        step.wait_ms = _parse_optional_int(wait_ms)
        db.commit()
    return RedirectResponse(
        url=f"/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}",
        status_code=HTTP_303_SEE_OTHER,
    )


@app.post(
    "/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}/steps/{step_id}/move"
)
def move_scenario_step(
    project_id: int,
    environment_id: int,
    scenario_id: int,
    step_id: int,
    direction: str = Form(...),
):
    with SessionLocal() as db:
        scenario = _get_scenario_or_404(db, environment_id, scenario_id)
        step = _get_scenario_step_or_404(db, scenario_id, step_id)
        steps = scenario.steps
        index = next(i for i, s in enumerate(steps) if s.id == step.id)

        if direction == "up" and index > 0:
            neighbor = steps[index - 1]
            step.position, neighbor.position = neighbor.position, step.position
        elif direction == "down" and index < len(steps) - 1:
            neighbor = steps[index + 1]
            step.position, neighbor.position = neighbor.position, step.position

        db.commit()
    return RedirectResponse(
        url=f"/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}",
        status_code=HTTP_303_SEE_OTHER,
    )


@app.post("/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}/run")
def run_scenario_route(project_id: int, environment_id: int, scenario_id: int):
    with SessionLocal() as db:
        scenario = _get_scenario_or_404(db, environment_id, scenario_id)
        if not scenario.steps:
            raise HTTPException(status_code=400, detail="Senaryoda hiç adım yok")
        run = execute_scenario(scenario)
        db.commit()
        db.refresh(run)
        run_id = run.id
    return RedirectResponse(
        url=f"/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}/runs/{run_id}",
        status_code=HTTP_303_SEE_OTHER,
    )


@app.get(
    "/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}/runs/{run_id}"
)
def scenario_run_detail(
    project_id: int, environment_id: int, scenario_id: int, run_id: int, request: Request
):
    with SessionLocal() as db:
        project = _get_project_or_404(db, project_id)
        environment = _get_environment_or_404(db, project_id, environment_id)
        scenario = _get_scenario_or_404(db, environment_id, scenario_id)
        run = _get_scenario_run_or_404(db, scenario_id, run_id)
        return templates.TemplateResponse(
            request,
            "scenario_run_detail.html",
            {"project": project, "environment": environment, "scenario": scenario, "run": run},
        )


@app.post("/projects/{project_id}/environments/{environment_id}/scenarios/{scenario_id}/delete")
def delete_scenario(project_id: int, environment_id: int, scenario_id: int):
    with SessionLocal() as db:
        scenario = _get_scenario_or_404(db, environment_id, scenario_id)
        db.delete(scenario)
        db.commit()
    shutil.rmtree(SCENARIO_SCREENSHOT_DIR / str(scenario_id), ignore_errors=True)
    return RedirectResponse(
        url=f"/projects/{project_id}/environments/{environment_id}", status_code=HTTP_303_SEE_OTHER
    )
