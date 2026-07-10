import json
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.models import CacheWarmCheck, Environment

GOWARM_BINARY = Path(__file__).resolve().parent.parent / "cache_warmer" / "bin" / "gowarm"
TIMEOUT_SECONDS = 300

DEFAULT_CONFIG = {
    "worker_count": 10,
    "method": "GET",
    "user_agent": "cmsplus-cache-warmer/1.0",
    "follow_index": True,
    "stop_on_error": False,
    "log_level": "warn",
    "limits": {"max_jobs": 20000, "max_combinations_per_url": 64},
}


def _reset_cache_warm_fields(environment: Environment, checked_at: datetime, error: str) -> None:
    environment.last_cache_warm_checked_at = checked_at
    environment.last_cache_warm_ok = False
    environment.last_cache_warm_total = None
    environment.last_cache_warm_success = None
    environment.last_cache_warm_failed = None
    environment.last_cache_warm_hit_ratio = None
    environment.last_cache_warm_error = error


def _failed_check(environment: Environment, checked_at: datetime, error: str, duration_ms=None) -> CacheWarmCheck:
    check = CacheWarmCheck(checked_at=checked_at, ok=False, error=error, duration_ms=duration_ms)
    _reset_cache_warm_fields(environment, checked_at, error)
    environment.cache_warm_checks.append(check)
    return check


def run_cache_warm_check(environment: Environment) -> CacheWarmCheck:
    checked_at = datetime.now(timezone.utc)
    start = time.monotonic()

    if not environment.cache_warm_sitemap_url or not environment.cache_warm_axes_yaml:
        return _failed_check(
            environment,
            checked_at,
            "Sitemap URL veya axes yapılandırması eksik (ortam ayarlarından doldurun)",
        )

    if not GOWARM_BINARY.exists():
        return _failed_check(
            environment,
            checked_at,
            "gowarm binary bulunamadı (cache_warmer/bin/gowarm derlenmeli, bkz. README)",
        )

    try:
        axes = yaml.safe_load(environment.cache_warm_axes_yaml)
        if not isinstance(axes, list) or not axes:
            raise ValueError("axes en az bir eleman içeren bir liste olmalı")
    except Exception as exc:
        return _failed_check(environment, checked_at, f"axes YAML hatası: {exc}"[:255])

    config = {
        **DEFAULT_CONFIG,
        "sitemap_url": environment.cache_warm_sitemap_url,
        "axes": axes,
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "config.yaml"
        summary_path = Path(tmp_dir) / "summary.json"
        config_path.write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")

        try:
            result = subprocess.run(
                [str(GOWARM_BINARY), "-config", str(config_path), "-summary-file", str(summary_path)],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )
            duration_ms = round((time.monotonic() - start) * 1000)

            if not summary_path.exists():
                stderr_lines = (result.stderr or "").strip().splitlines()
                raise RuntimeError(stderr_lines[-1] if stderr_lines else "gowarm çalıştırılamadı")

            summary = json.loads(summary_path.read_text(encoding="utf-8"))

            check = CacheWarmCheck(
                checked_at=checked_at,
                ok=True,
                error=None,
                duration_ms=duration_ms,
                url_count=summary.get("url_count"),
                total_jobs=summary.get("total_jobs"),
                success=summary.get("success"),
                failed=summary.get("failed"),
                cache_hits=summary.get("cache_hits"),
                cache_misses=summary.get("cache_misses"),
                cache_bypass=summary.get("cache_bypass"),
                unknown_cache_state=summary.get("unknown_cache_state"),
                hit_ratio=summary.get("hit_ratio"),
                summary_json=json.dumps(summary, ensure_ascii=False),
            )
            environment.last_cache_warm_checked_at = checked_at
            environment.last_cache_warm_ok = True
            environment.last_cache_warm_total = summary.get("total_jobs")
            environment.last_cache_warm_success = summary.get("success")
            environment.last_cache_warm_failed = summary.get("failed")
            environment.last_cache_warm_hit_ratio = summary.get("hit_ratio")
            environment.last_cache_warm_error = None
            environment.cache_warm_checks.append(check)
            return check
        except subprocess.TimeoutExpired:
            duration_ms = round((time.monotonic() - start) * 1000)
            error_message = f"gowarm {TIMEOUT_SECONDS} saniyede zaman aşımına uğradı"
            return _failed_check(environment, checked_at, error_message, duration_ms)
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000)
            error_message = str(exc).splitlines()[0][:255]
            return _failed_check(environment, checked_at, error_message, duration_ms)
