import json
import time
from datetime import datetime, timezone

import httpx

from app.models import Environment, HealthCheck

RESPONSE_BODY_SNIPPET_LENGTH = 5000


def run_health_check(environment: Environment) -> HealthCheck:
    checked_at = datetime.now(timezone.utc)
    start = time.monotonic()
    try:
        response = httpx.get(environment.url, timeout=10.0, follow_redirects=True)
        elapsed_ms = round((time.monotonic() - start) * 1000)
        ok = response.status_code < 400
        check = HealthCheck(
            checked_at=checked_at,
            ok=ok,
            status_code=response.status_code,
            response_ms=elapsed_ms,
            error=None,
            content_type=response.headers.get("content-type"),
            response_headers=json.dumps(dict(response.headers), ensure_ascii=False),
            response_body=response.text[:RESPONSE_BODY_SNIPPET_LENGTH] if response.text else None,
        )
        environment.last_status_code = response.status_code
        environment.last_response_ms = elapsed_ms
        environment.last_check_ok = ok
        environment.last_check_error = None
    except httpx.RequestError as exc:
        error_message = str(exc)[:255]
        check = HealthCheck(
            checked_at=checked_at,
            ok=False,
            status_code=None,
            response_ms=None,
            error=error_message,
            content_type=None,
            response_headers=None,
            response_body=None,
        )
        environment.last_status_code = None
        environment.last_response_ms = None
        environment.last_check_ok = False
        environment.last_check_error = error_message
    environment.last_checked_at = checked_at
    environment.health_checks.append(check)
    return check
