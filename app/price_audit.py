import json
import re
import time
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse

import pandas as pd
from playwright.sync_api import sync_playwright

from app.models import Environment, PriceAudit
from app.scenario_runner import _build_url, _values_equal

SCROLL_STABLE_ROUNDS = 4
SCROLL_MAX_ITERATIONS = 60
SCROLL_WAIT_MS = 900
NAVIGATE_TIMEOUT_MS = 20000
STEP_TIMEOUT_MS = 10000
# Color/capacity selection multiplies the work per product (each combination is its
# own navigation-free variant read), so this allows a generous overall ceiling.
MAX_RUNTIME_SECONDS = 1800

UPC_COLUMN_ALIASES = {"upc code", "upc"}
CASH_COLUMN_ALIASES = {"peşin fiyat", "pesin fiyat"}
INSTALLMENT_COLUMN_ALIASES = {"taksitli fiyat"}


def _cell_to_str(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _find_column(columns, aliases) -> Optional[str]:
    for col in columns:
        if str(col).strip().lower() in aliases:
            return col
    return None


def _parse_excel(excel_bytes: bytes) -> dict:
    """Returns {upc: {"cash": str, "installment": str}}; raises ValueError on bad headers."""
    df = pd.read_excel(BytesIO(excel_bytes), engine="openpyxl", dtype=str)
    upc_col = _find_column(df.columns, UPC_COLUMN_ALIASES)
    cash_col = _find_column(df.columns, CASH_COLUMN_ALIASES)
    installment_col = _find_column(df.columns, INSTALLMENT_COLUMN_ALIASES)
    missing = [
        label
        for label, col in (
            ("UPC Code", upc_col),
            ("Peşin Fiyat", cash_col),
            ("Taksitli Fiyat", installment_col),
        )
        if col is None
    ]
    if missing:
        found = ", ".join(str(c) for c in df.columns)
        raise ValueError(f"Excel'de şu kolonlar bulunamadı: {', '.join(missing)}. Bulunan kolonlar: {found}")

    rows = {}
    for _, row in df.iterrows():
        upc = _cell_to_str(row[upc_col])
        if not upc:
            continue
        rows[upc] = {
            "cash": _cell_to_str(row[cash_col]),
            "installment": _cell_to_str(row[installment_col]),
        }
    return rows


def _matching_hrefs(page) -> list:
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))"
    )


def _matched_unique_paths(page, link_pattern: re.Pattern) -> set:
    """Counts only product-link matches (not every <a> on the page) so that static
    nav/footer links don't dilute the scroll-stability signal below."""
    paths = set()
    for href in _matching_hrefs(page):
        if href and link_pattern.search(href):
            absolute = urljoin(page.url, href)
            paths.add(urlparse(absolute)._replace(query="", fragment="").geturl())
    return paths


def _collect_product_urls(page, listing_url: str, link_pattern: re.Pattern) -> list:
    page.goto(listing_url, wait_until="domcontentloaded", timeout=NAVIGATE_TIMEOUT_MS)
    page.wait_for_timeout(1500)

    prev_count = -1
    stable_rounds = 0
    for _ in range(SCROLL_MAX_ITERATIONS):
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(SCROLL_WAIT_MS)
        count = len(_matched_unique_paths(page, link_pattern))
        if count == prev_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        prev_count = count
        if stable_rounds >= SCROLL_STABLE_ROUNDS:
            break

    seen_paths = set()
    urls = []
    for href in _matching_hrefs(page):
        if not href or not link_pattern.search(href):
            continue
        absolute = urljoin(page.url, href)
        path_only = urlparse(absolute)._replace(query="", fragment="").geturl()
        if path_only in seen_paths:
            continue
        seen_paths.add(path_only)
        urls.append(absolute)
    return urls


def _extract_upc_from_url(url: str) -> Optional[str]:
    values = parse_qs(urlparse(url).query).get("upc")
    return values[0] if values else None


def _wait_for_upc(page, previous: Optional[str] = None, timeout_ms: int = 8000, poll_ms: int = 300) -> Optional[str]:
    """The product detail page appends/updates `upc=` in the URL client-side,
    ~1.5-2s after load or after a color/capacity selection — poll instead of a
    fixed sleep, and require a value different from `previous` so a stale
    not-yet-updated upc isn't mistaken for the new variant's."""
    elapsed = 0
    while elapsed <= timeout_ms:
        upc = _extract_upc_from_url(page.url)
        if upc and upc != previous:
            return upc
        page.wait_for_timeout(poll_ms)
        elapsed += poll_ms
    return _extract_upc_from_url(page.url)


def _extract_price(page, click_selector: str, price_selector: str) -> str:
    page.click(click_selector, timeout=STEP_TIMEOUT_MS)
    page.wait_for_timeout(800)
    return page.locator(price_selector).first.inner_text().strip()


def _variant_option_count(page, selector: Optional[str]) -> int:
    return page.locator(selector).count() if selector else 0


def _click_variant_option(page, selector: str, index: int) -> None:
    page.locator(selector).nth(index).click(force=True, timeout=STEP_TIMEOUT_MS)


def _failed_audit(environment: Environment, created_at: datetime, excel_filename: str, error: str) -> PriceAudit:
    """Creates a new, already-failed PriceAudit — used for validation errors caught
    up front (before any background thread/browser is started)."""
    audit = PriceAudit(
        created_at=created_at, excel_filename=excel_filename, status="failed", ok=False, error=error
    )
    environment.last_price_audit_at = created_at
    environment.last_price_audit_ok = False
    environment.last_price_audit_error = error
    environment.last_price_audit_matched = None
    environment.last_price_audit_mismatched = None
    environment.price_audits.append(audit)
    return audit


def _mark_failed(environment: Environment, audit: PriceAudit, error: str) -> None:
    """Fails an already-created (status="running") audit row in place."""
    audit.status = "failed"
    audit.ok = False
    audit.error = error
    environment.last_price_audit_at = audit.created_at
    environment.last_price_audit_ok = False
    environment.last_price_audit_error = error
    environment.last_price_audit_matched = None
    environment.last_price_audit_mismatched = None


def start_price_audit(environment: Environment, excel_bytes: bytes, excel_filename: str) -> PriceAudit:
    """Runs the fast, synchronous validation (config present, regex/Excel parse ok)
    and either returns an already-failed audit, or a new status="running" row that
    the caller should commit and then hand off to `run_price_audit_background`."""
    created_at = datetime.now(timezone.utc)

    required = (
        environment.price_audit_listing_path,
        environment.price_audit_link_pattern,
        environment.price_audit_upfront_selector,
        environment.price_audit_financing_selector,
        environment.price_audit_price_selector,
    )
    if not all(required):
        return _failed_audit(
            environment, created_at, excel_filename,
            "Fiyat denetimi yapılandırılmadı (ortam ayarlarından doldurun)",
        )

    try:
        re.compile(environment.price_audit_link_pattern)
    except re.error as exc:
        return _failed_audit(environment, created_at, excel_filename, f"Ürün link deseni geçersiz: {exc}"[:255])

    try:
        _parse_excel(excel_bytes)
    except Exception as exc:
        return _failed_audit(environment, created_at, excel_filename, str(exc).splitlines()[0][:255])

    audit = PriceAudit(created_at=created_at, excel_filename=excel_filename, status="running", ok=False)
    environment.price_audits.append(audit)
    return audit


def run_price_audit_background(environment_id: int, audit_id: int, excel_bytes: bytes) -> None:
    """Entry point for the background thread spawned by the upload route. Owns its
    own DB session (SQLAlchemy sessions aren't safe to share across threads)."""
    from app.database import SessionLocal

    with SessionLocal() as db:
        environment = db.get(Environment, environment_id)
        audit = db.get(PriceAudit, audit_id)
        if environment is None or audit is None:
            return
        try:
            _run_price_audit_core(db, environment, audit, excel_bytes)
        except Exception as exc:
            _mark_failed(environment, audit, str(exc).splitlines()[0][:255])
            db.commit()


def _run_price_audit_core(db, environment: Environment, audit: PriceAudit, excel_bytes: bytes) -> None:
    start = time.monotonic()
    excel_rows = _parse_excel(excel_bytes)
    link_pattern = re.compile(environment.price_audit_link_pattern)
    listing_url = _build_url(environment.url, environment.price_audit_listing_path)

    matched = []
    errors = []
    site_upcs: dict = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            try:
                product_urls = _collect_product_urls(page, listing_url, link_pattern)
            except Exception as exc:
                _mark_failed(
                    environment, audit, f"Listeleme sayfası taranamadı: {exc}".splitlines()[0][:255]
                )
                db.commit()
                return

            audit.total_products = len(product_urls)
            db.commit()

            for product_index, product_url in enumerate(product_urls):
                audit.completed_products = product_index
                audit.current_product_label = product_url
                db.commit()
                if time.monotonic() - start > MAX_RUNTIME_SECONDS:
                    errors.append({"url": product_url, "err": "Zaman aşımı - kalan ürünler atlandı"})
                    continue
                try:
                    page.goto(product_url, wait_until="domcontentloaded", timeout=NAVIGATE_TIMEOUT_MS)
                    default_upc = _wait_for_upc(page)
                    if not default_upc:
                        raise RuntimeError("UPC parametresi URL'de bulunamadı")
                except Exception as exc:
                    errors.append({"url": product_url, "err": str(exc).splitlines()[0][:255]})
                    # A failed/timed-out navigation can leave the browser mid-flight in a
                    # state that "interrupts" the *next* product's goto() with a cascading
                    # error, silently wiping out the rest of the run. Recover with a fresh
                    # page so one bad product can't take the rest down with it.
                    try:
                        page.close()
                    except Exception:
                        pass
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    continue

                color_count = _variant_option_count(page, environment.price_audit_color_selector)
                capacity_count = _variant_option_count(page, environment.price_audit_capacity_selector)
                color_indices = list(range(color_count)) if color_count else [None]
                capacity_indices = list(range(capacity_count)) if capacity_count else [None]

                for color_index in color_indices:
                    if time.monotonic() - start > MAX_RUNTIME_SECONDS:
                        errors.append({"url": product_url, "err": "Zaman aşımı - kalan varyasyonlar atlandı"})
                        break

                    color_upc = default_upc
                    if color_index is not None:
                        try:
                            _click_variant_option(page, environment.price_audit_color_selector, color_index)
                            color_upc = _wait_for_upc(page, previous=default_upc)
                        except Exception as exc:
                            errors.append({
                                "url": product_url,
                                "err": f"renk seçilemedi (index={color_index}): {exc}".splitlines()[0][:255],
                            })
                            continue

                    capacity_baseline_upc = color_upc
                    for capacity_index in capacity_indices:
                        if time.monotonic() - start > MAX_RUNTIME_SECONDS:
                            errors.append({"url": product_url, "err": "Zaman aşımı - kalan varyasyonlar atlandı"})
                            break

                        variant_upc = capacity_baseline_upc
                        if capacity_index is not None:
                            try:
                                _click_variant_option(page, environment.price_audit_capacity_selector, capacity_index)
                                variant_upc = _wait_for_upc(page, previous=capacity_baseline_upc)
                            except Exception as exc:
                                errors.append({
                                    "url": product_url,
                                    "err": f"kapasite seçilemedi (index={capacity_index}): {exc}".splitlines()[0][:255],
                                })
                                continue
                            capacity_baseline_upc = variant_upc

                        if not variant_upc:
                            errors.append({"url": product_url, "err": "Varyasyon için UPC bulunamadı"})
                            continue

                        try:
                            site_cash = _extract_price(
                                page, environment.price_audit_upfront_selector, environment.price_audit_price_selector
                            )
                            site_installment = _extract_price(
                                page, environment.price_audit_financing_selector, environment.price_audit_price_selector
                            )
                        except Exception as exc:
                            errors.append({"url": product_url, "err": str(exc).splitlines()[0][:255]})
                            continue

                        site_upcs[variant_upc] = {
                            "cash": site_cash,
                            "installment": site_installment,
                            "url": page.url,
                        }

            audit.completed_products = len(product_urls)
            db.commit()
        finally:
            browser.close()

    for upc, site_data in site_upcs.items():
        excel_data = excel_rows.get(upc)
        if excel_data is None:
            continue
        matched.append({
            "upc": upc,
            "product_url": site_data["url"],
            "excel_cash": excel_data["cash"],
            "site_cash": site_data["cash"],
            "cash_match": _values_equal(excel_data["cash"], site_data["cash"]),
            "excel_installment": excel_data["installment"],
            "site_installment": site_data["installment"],
            "installment_match": _values_equal(excel_data["installment"], site_data["installment"]),
        })

    only_in_site = [
        {"upc": upc, "site_cash": data["cash"], "site_installment": data["installment"], "product_url": data["url"]}
        for upc, data in site_upcs.items()
        if upc not in excel_rows
    ]
    only_in_excel = [
        {"upc": upc, "excel_cash": data["cash"], "excel_installment": data["installment"]}
        for upc, data in excel_rows.items()
        if upc not in site_upcs
    ]

    mismatched_count = sum(1 for item in matched if not item["cash_match"] or not item["installment_match"])
    duration_ms = round((time.monotonic() - start) * 1000)

    results = {"matched": matched, "only_in_site": only_in_site, "only_in_excel": only_in_excel, "errors": errors}

    audit.status = "completed"
    audit.ok = True
    audit.error = None
    audit.duration_ms = duration_ms
    audit.product_count = len(site_upcs)
    audit.excel_row_count = len(excel_rows)
    audit.matched_count = len(matched)
    audit.mismatched_count = mismatched_count
    audit.only_in_site_count = len(only_in_site)
    audit.only_in_excel_count = len(only_in_excel)
    audit.results_json = json.dumps(results, ensure_ascii=False)
    audit.current_product_label = None

    environment.last_price_audit_at = audit.created_at
    environment.last_price_audit_ok = True
    environment.last_price_audit_error = None
    environment.last_price_audit_matched = len(matched)
    environment.last_price_audit_mismatched = mismatched_count
    db.commit()
