import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
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
    "save_value": "Değer kaydet",
    "compare_values": "Değerleri karşılaştır",
}

OPERATOR_LABELS = {
    ">=": "en az",
    "<=": "en fazla",
    "==": "tam olarak",
    ">": "daha fazla",
    "<": "daha az",
    "!=": "eşit değil",
}


def _build_url(base_url: str, path: str) -> str:
    """Combines the environment's domain with an absolute path, ignoring any
    existing path segment on base_url (so a "/mobile" step always means
    "https://domain/mobile", not "https://domain/existing-path/mobile")."""
    parsed_base = urlparse(base_url)
    normalized_path = "/" + (path or "").strip().lstrip("/")
    return urlunparse((parsed_base.scheme, parsed_base.netloc, normalized_path, "", "", ""))


def describe_step(step: ScenarioStep, variables: Optional[dict] = None) -> str:
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
    if step.step_type == "save_value":
        base = f"'{step.selector}' öğesinin değerini '{step.value}' değişkenine kaydet"
        if variables is not None and step.value in variables:
            base += f" → '{_truncate(variables[step.value])}'"
        return base
    if step.step_type == "compare_values":
        relation = "eşit olmadığını" if step.operator == "!=" else "eşit olduğunu"
        base = f"'{step.value}' değişkeni ile '{step.value2}' değişkeninin {relation} kontrol et"
        if variables is not None:
            val_a = variables.get(step.value)
            val_b = variables.get(step.value2)
            if val_a is not None and val_b is not None:
                base += (
                    f" ('{step.value}'='{_truncate(val_a)}', "
                    f"'{step.value2}'='{_truncate(val_b)}')"
                )
        return base
    return step.step_type


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _compare(actual, operator: str, expected) -> bool:
    if operator == ">=":
        return actual >= expected
    if operator == "<=":
        return actual <= expected
    if operator == "==":
        return actual == expected
    if operator == "!=":
        return actual != expected
    if operator == ">":
        return actual > expected
    if operator == "<":
        return actual < expected
    raise ValueError(f"Bilinmeyen operatör: {operator}")


def _parse_number(text: str):
    """Extracts a locale-agnostic number from strings like "$1,499", "1499.00 CAD"
    or "1.499,00" (treats the separator immediately before 1-2 trailing digits as
    the decimal point; any other comma/dot is a thousands separator)."""
    match = re.search(r"\d[\d.,\s]*", text)
    if not match:
        return None
    raw = match.group(0).replace(" ", "").replace("\xa0", "")
    last_sep_pos = max(raw.rfind(","), raw.rfind("."))
    if last_sep_pos == -1:
        cleaned = raw
    else:
        fraction_len = len(raw) - last_sep_pos - 1
        integer_part = raw[:last_sep_pos].replace(",", "").replace(".", "")
        fraction_part = raw[last_sep_pos + 1 :]
        if fraction_len in (1, 2):
            cleaned = f"{integer_part}.{fraction_part}"
        else:
            cleaned = integer_part + fraction_part
    try:
        return float(cleaned)
    except ValueError:
        return None


def _values_equal(val_a: str, val_b: str) -> bool:
    num_a, num_b = _parse_number(val_a), _parse_number(val_b)
    if num_a is not None and num_b is not None:
        return abs(num_a - num_b) < 1e-9
    return val_a == val_b


def _execute_step(page, base_url: str, step: ScenarioStep, variables: dict) -> None:
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
    elif step.step_type == "save_value":
        locator = page.locator(step.selector)
        if locator.count() == 0:
            raise AssertionError(f"'{step.selector}' seçicisine uyan eleman bulunamadı")
        first = locator.first
        tag_name = first.evaluate("el => el.tagName.toLowerCase()")
        if tag_name in ("input", "textarea", "select"):
            extracted = first.input_value()
        else:
            extracted = first.inner_text()
        variables[step.value] = extracted.strip()
    elif step.step_type == "compare_values":
        if step.value not in variables or step.value2 not in variables:
            missing = step.value if step.value not in variables else step.value2
            raise AssertionError(f"'{missing}' değişkeni bu ana kadar kaydedilmedi")
        val_a = variables[step.value]
        val_b = variables[step.value2]
        operator = step.operator or "=="
        equal = _values_equal(val_a, val_b)
        result = equal if operator == "==" else not equal
        if not result:
            expectation = "eşit olmamalıydı" if operator == "!=" else "eşit olmalıydı"
            raise AssertionError(
                f"'{step.value}' ({val_a}) ile '{step.value2}' ({val_b}) {expectation}"
            )
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
    variables: dict = {}

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
                    _execute_step(page, base_url, step, variables)
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

                if step.step_type in ("save_value", "compare_values"):
                    result.description = describe_step(step, variables)

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
