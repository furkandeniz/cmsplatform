import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from playwright.sync_api import sync_playwright

from app.models import Scenario, ScenarioRun, ScenarioStep, ScenarioStepResult

STATIC_DIR = Path("app/static")
SCREENSHOT_DIR = STATIC_DIR / "uploads" / "scenario-runs"

STEP_TIMEOUT_MS = 10000
NAVIGATE_TIMEOUT_MS = 20000

STEP_TYPE_LABELS = {
    "navigate": "Sayfaya git",
    "click": "Tıkla",
    "fill": "Alanı doldur",
    "select_option": "Seçim yap",
    "wait": "Bekle",
    "assert_text": "Metin var mı kontrol et",
    "assert_no_text": "Metin yok mu kontrol et",
    "assert_element": "Eleman var mı kontrol et",
    "assert_count": "Eleman sayısını kontrol et",
    "screenshot": "Ekran görüntüsü al",
}

OPERATOR_LABELS = {
    ">=": "en az",
    "<=": "en fazla",
    "==": "tam olarak",
    ">": "daha fazla",
    "<": "daha az",
}


def _build_url(base_url: str, path: str) -> str:
    """Combines the environment's domain with an absolute path, ignoring any
    existing path segment on base_url (so a "/mobile" step always means
    "https://domain/mobile", not "https://domain/existing-path/mobile")."""
    parsed_base = urlparse(base_url)
    normalized_path = "/" + (path or "").strip().lstrip("/")
    return urlunparse((parsed_base.scheme, parsed_base.netloc, normalized_path, "", "", ""))


def describe_step(step: ScenarioStep) -> str:
    if step.step_type == "navigate":
        return f"'{step.path}' sayfasına git"
    if step.step_type == "click":
        return f"'{step.selector}' öğesine tıkla"
    if step.step_type == "fill":
        return f"'{step.selector}' alanına '{step.value}' yaz"
    if step.step_type == "select_option":
        return f"'{step.selector}' seçiminde '{step.value}' seç"
    if step.step_type == "wait":
        return f"{step.wait_ms or 0} ms bekle"
    if step.step_type == "assert_text":
        return f"Sayfada '{step.value}' metni olduğunu kontrol et"
    if step.step_type == "assert_no_text":
        return f"Sayfada '{step.value}' metni olmadığını kontrol et"
    if step.step_type == "assert_element":
        return f"'{step.selector}' öğesinin var olduğunu kontrol et"
    if step.step_type == "assert_count":
        operator_label = OPERATOR_LABELS.get(step.operator, step.operator)
        return f"'{step.selector}' eleman sayısı {operator_label} {step.count} mi kontrol et"
    if step.step_type == "screenshot":
        return "Ekran görüntüsü al"
    return step.step_type


def _compare(actual: int, operator: str, expected: int) -> bool:
    if operator == ">=":
        return actual >= expected
    if operator == "<=":
        return actual <= expected
    if operator == "==":
        return actual == expected
    if operator == ">":
        return actual > expected
    if operator == "<":
        return actual < expected
    raise ValueError(f"Bilinmeyen operatör: {operator}")


def _execute_step(page, base_url: str, step: ScenarioStep) -> None:
    if step.step_type == "navigate":
        page.goto(_build_url(base_url, step.path), wait_until="load", timeout=NAVIGATE_TIMEOUT_MS)
    elif step.step_type == "click":
        page.click(step.selector, timeout=STEP_TIMEOUT_MS)
    elif step.step_type == "fill":
        page.fill(step.selector, step.value or "", timeout=STEP_TIMEOUT_MS)
    elif step.step_type == "select_option":
        page.select_option(step.selector, step.value, timeout=STEP_TIMEOUT_MS)
    elif step.step_type == "wait":
        page.wait_for_timeout(step.wait_ms or 1000)
    elif step.step_type == "assert_text":
        content = page.inner_text("body")
        if (step.value or "").lower() not in content.lower():
            raise AssertionError(f"Sayfada '{step.value}' metni bulunamadı")
    elif step.step_type == "assert_no_text":
        content = page.inner_text("body")
        if (step.value or "").lower() in content.lower():
            raise AssertionError(f"Sayfada '{step.value}' metni bulunmamalıydı ama bulundu")
    elif step.step_type == "assert_element":
        count = page.locator(step.selector).count()
        if count == 0:
            raise AssertionError(f"'{step.selector}' seçicisine uyan eleman bulunamadı")
    elif step.step_type == "assert_count":
        actual = page.locator(step.selector).count()
        if not _compare(actual, step.operator, step.count):
            raise AssertionError(
                f"'{step.selector}' eleman sayısı {actual}, beklenen {step.operator} {step.count}"
            )
    elif step.step_type == "screenshot":
        pass
    else:
        raise ValueError(f"Bilinmeyen adım türü: {step.step_type}")


def run_scenario(scenario: Scenario) -> ScenarioRun:
    run_dir = SCREENSHOT_DIR / str(scenario.id)
    run_dir.mkdir(parents=True, exist_ok=True)

    run = ScenarioRun(scenario_id=scenario.id, run_at=datetime.now(timezone.utc))
    base_url = scenario.environment.url
    overall_ok = True
    first_error = None
    run_start = time.monotonic()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            for step in scenario.steps:
                step_start = time.monotonic()
                result = ScenarioStepResult(
                    position=step.position,
                    step_type=step.step_type,
                    description=describe_step(step),
                )

                try:
                    _execute_step(page, base_url, step)
                    result.ok = True
                    if step.step_type == "screenshot":
                        screenshot_path = run_dir / f"{uuid.uuid4().hex}.png"
                        page.screenshot(path=str(screenshot_path), full_page=True)
                        result.screenshot_path = str(screenshot_path.relative_to(STATIC_DIR))
                except Exception as exc:
                    result.ok = False
                    result.error = str(exc).splitlines()[0][:255]
                    overall_ok = False
                    if first_error is None:
                        first_error = result.error
                    try:
                        screenshot_path = run_dir / f"{uuid.uuid4().hex}_fail.png"
                        page.screenshot(path=str(screenshot_path), full_page=True)
                        result.screenshot_path = str(screenshot_path.relative_to(STATIC_DIR))
                    except Exception:
                        pass

                result.duration_ms = round((time.monotonic() - step_start) * 1000)
                run.step_results.append(result)

                if not result.ok:
                    break
        finally:
            browser.close()

    run.ok = overall_ok
    run.error = first_error
    run.duration_ms = round((time.monotonic() - run_start) * 1000)
    scenario.runs.append(run)
    return run
