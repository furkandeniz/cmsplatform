import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models import Environment, LighthouseCheck

LIGHTHOUSE_DIR = Path(__file__).resolve().parent.parent / "lighthouse"
RUN_SCRIPT = LIGHTHOUSE_DIR / "run.mjs"
TIMEOUT_SECONDS = 90

CATEGORY_IDS = ["performance", "accessibility", "best-practices", "seo"]


def _extract_failing_audits(report: dict, limit: int = 20) -> list:
    """Collects every non-perfect, scoreable audit across all categories,
    worst-first, so the detail page can show what actually needs fixing."""
    audits = report.get("audits", {})
    categories = report.get("categories", {})
    seen = set()
    results = []
    for category_id, category in categories.items():
        for ref in category.get("auditRefs", []):
            audit_id = ref.get("id")
            if audit_id in seen:
                continue
            audit = audits.get(audit_id)
            if not audit or audit.get("scoreDisplayMode") not in ("binary", "numeric"):
                continue
            score = audit.get("score")
            if score is None or score >= 1:
                continue
            seen.add(audit_id)
            results.append({
                "category": category_id,
                "id": audit_id,
                "title": audit.get("title"),
                "description": (audit.get("description") or "")[:400],
                "score": score,
                "display_value": audit.get("displayValue"),
            })
    results.sort(key=lambda item: item["score"])
    return results[:limit]


def _score_of(categories: dict, category_id: str) -> Optional[int]:
    category = categories.get(category_id)
    if not category or category.get("score") is None:
        return None
    return round(category["score"] * 100)


def _reset_lighthouse_fields(environment: Environment, checked_at: datetime, error: str) -> None:
    environment.last_lighthouse_checked_at = checked_at
    environment.last_lighthouse_ok = False
    environment.last_lighthouse_performance = None
    environment.last_lighthouse_accessibility = None
    environment.last_lighthouse_best_practices = None
    environment.last_lighthouse_seo = None
    environment.last_lighthouse_error = error


def run_lighthouse_check(environment: Environment) -> LighthouseCheck:
    checked_at = datetime.now(timezone.utc)
    start = time.monotonic()

    if shutil.which("node") is None:
        error_message = "node bulunamadı (Lighthouse için Node.js kurulu olmalı)"
        check = LighthouseCheck(checked_at=checked_at, ok=False, error=error_message)
        _reset_lighthouse_fields(environment, checked_at, error_message)
        environment.lighthouse_checks.append(check)
        return check

    try:
        result = subprocess.run(
            ["node", str(RUN_SCRIPT), environment.url],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            cwd=str(LIGHTHOUSE_DIR),
        )
        duration_ms = round((time.monotonic() - start) * 1000)

        if result.returncode != 0:
            stderr_lines = (result.stderr or "").strip().splitlines()
            raise RuntimeError(stderr_lines[-1] if stderr_lines else "Lighthouse çalıştırılamadı")

        report = json.loads(result.stdout)
        runtime_error = report.get("runtimeError")
        if runtime_error:
            raise RuntimeError(runtime_error.get("message", "Lighthouse runtime hatası"))

        categories = report.get("categories", {})
        performance = _score_of(categories, "performance")
        accessibility = _score_of(categories, "accessibility")
        best_practices = _score_of(categories, "best-practices")
        seo = _score_of(categories, "seo")

        check = LighthouseCheck(
            checked_at=checked_at,
            ok=True,
            error=None,
            duration_ms=duration_ms,
            performance_score=performance,
            accessibility_score=accessibility,
            best_practices_score=best_practices,
            seo_score=seo,
            audits=json.dumps(_extract_failing_audits(report), ensure_ascii=False),
        )
        environment.last_lighthouse_checked_at = checked_at
        environment.last_lighthouse_ok = True
        environment.last_lighthouse_performance = performance
        environment.last_lighthouse_accessibility = accessibility
        environment.last_lighthouse_best_practices = best_practices
        environment.last_lighthouse_seo = seo
        environment.last_lighthouse_error = None
    except subprocess.TimeoutExpired:
        duration_ms = round((time.monotonic() - start) * 1000)
        error_message = f"Lighthouse taraması {TIMEOUT_SECONDS} saniyede zaman aşımına uğradı"
        check = LighthouseCheck(checked_at=checked_at, ok=False, error=error_message, duration_ms=duration_ms)
        _reset_lighthouse_fields(environment, checked_at, error_message)
    except Exception as exc:
        duration_ms = round((time.monotonic() - start) * 1000)
        error_message = str(exc).splitlines()[0][:255]
        check = LighthouseCheck(checked_at=checked_at, ok=False, error=error_message, duration_ms=duration_ms)
        _reset_lighthouse_fields(environment, checked_at, error_message)

    environment.lighthouse_checks.append(check)
    return check
