import json
import time
from datetime import datetime, timezone
from typing import Optional

from playwright.sync_api import sync_playwright

from app.models import Environment, SeoCheck

EXTRACTION_SCRIPT = """
() => {
  const getMeta = (selector, attr) => {
    const el = document.querySelector(selector);
    return el ? el.getAttribute(attr) : null;
  };
  const images = Array.from(document.querySelectorAll('img'));
  const h1s = Array.from(document.querySelectorAll('h1')).map(el => el.innerText.trim()).filter(Boolean);
  const links = Array.from(document.querySelectorAll('a[href]'));
  const currentHost = location.hostname;
  let internalLinks = 0;
  let externalLinks = 0;
  links.forEach((a) => {
    try {
      const u = new URL(a.getAttribute('href'), location.href);
      if (u.hostname === currentHost) internalLinks += 1;
      else externalLinks += 1;
    } catch (e) {
      /* ignore unparsable hrefs (mailto:, tel:, javascript:, etc.) */
    }
  });
  const bodyText = document.body ? document.body.innerText : '';
  const words = bodyText.trim().length ? bodyText.trim().split(/\\s+/) : [];
  return {
    title: document.title || null,
    lang: document.documentElement.getAttribute('lang'),
    meta_description: getMeta('meta[name="description"]', 'content'),
    canonical: getMeta('link[rel="canonical"]', 'href'),
    meta_robots: getMeta('meta[name="robots"]', 'content'),
    viewport: getMeta('meta[name="viewport"]', 'content'),
    og_title: getMeta('meta[property="og:title"]', 'content'),
    og_description: getMeta('meta[property="og:description"]', 'content'),
    og_image: getMeta('meta[property="og:image"]', 'content'),
    h1_count: h1s.length,
    h1_text: h1s[0] || null,
    image_count: images.length,
    images_missing_alt: images.filter((img) => {
      const alt = img.getAttribute('alt');
      return alt === null || alt.trim() === '';
    }).length,
    internal_link_count: internalLinks,
    external_link_count: externalLinks,
    structured_data_count: document.querySelectorAll('script[type="application/ld+json"]').length,
    word_count: words.length,
  };
}
"""


def _truncate(value: Optional[str], length: int) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    return value[:length]


def _compute_issues(data: dict) -> list:
    """Returns a list of (message, score_weight) tuples for every SEO issue found."""
    issues = []

    title = (data.get("title") or "").strip()
    if not title:
        issues.append(("Title etiketi eksik", 15))
    elif not (30 <= len(title) <= 60):
        issues.append((f"Title uzunluğu ideal aralıkta değil ({len(title)} karakter, ideal 30-60)", 5))

    meta_description = (data.get("meta_description") or "").strip()
    if not meta_description:
        issues.append(("Meta description eksik", 10))
    elif not (120 <= len(meta_description) <= 160):
        issues.append((
            f"Meta description uzunluğu ideal aralıkta değil ({len(meta_description)} karakter, ideal 120-160)",
            5,
        ))

    h1_count = data.get("h1_count") or 0
    if h1_count == 0:
        issues.append(("H1 etiketi yok", 15))
    elif h1_count > 1:
        issues.append((f"Birden fazla H1 etiketi var ({h1_count})", 5))

    if not data.get("canonical"):
        issues.append(("Canonical URL eksik", 5))

    meta_robots = (data.get("meta_robots") or "").lower()
    if "noindex" in meta_robots:
        issues.append(("Sayfa noindex olarak işaretli", 25))

    image_count = data.get("image_count") or 0
    missing_alt = data.get("images_missing_alt") or 0
    if image_count > 0 and missing_alt > 0:
        issues.append((f"{missing_alt}/{image_count} görselde alt metni eksik", 10))

    if not data.get("viewport"):
        issues.append(("Viewport meta etiketi eksik (mobil uyumluluk)", 10))

    if not data.get("lang"):
        issues.append(("HTML lang attribute eksik", 5))

    if not data.get("og_title") or not data.get("og_description"):
        issues.append(("Open Graph etiketleri eksik/yetersiz", 5))

    if not data.get("structured_data_count"):
        issues.append(("Structured data (JSON-LD) bulunamadı", 5))

    word_count = data.get("word_count") or 0
    if word_count < 300:
        issues.append((f"İçerik az olabilir ({word_count} kelime)", 5))

    return issues


def _reset_seo_fields(environment: Environment, checked_at: datetime, error: str) -> None:
    environment.last_seo_checked_at = checked_at
    environment.last_seo_ok = False
    environment.last_seo_score = None
    environment.last_seo_issue_count = None
    environment.last_seo_error = error


def run_seo_check(environment: Environment) -> SeoCheck:
    checked_at = datetime.now(timezone.utc)
    start = time.monotonic()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                response = page.goto(environment.url, wait_until="load", timeout=20000)
                status_code = response.status if response else None
                data = page.evaluate(EXTRACTION_SCRIPT)
            finally:
                browser.close()

        load_time_ms = round((time.monotonic() - start) * 1000)
        issues = _compute_issues(data)
        score = max(0, 100 - sum(weight for _, weight in issues))

        check = SeoCheck(
            checked_at=checked_at,
            ok=True,
            error=None,
            status_code=status_code,
            load_time_ms=load_time_ms,
            score=score,
            title=_truncate(data.get("title"), 500),
            meta_description=data.get("meta_description"),
            canonical_url=_truncate(data.get("canonical"), 500),
            meta_robots=_truncate(data.get("meta_robots"), 255),
            h1_count=data.get("h1_count"),
            h1_text=_truncate(data.get("h1_text"), 500),
            image_count=data.get("image_count"),
            images_missing_alt=data.get("images_missing_alt"),
            internal_link_count=data.get("internal_link_count"),
            external_link_count=data.get("external_link_count"),
            has_viewport=bool(data.get("viewport")),
            lang=_truncate(data.get("lang"), 20),
            og_title=_truncate(data.get("og_title"), 500),
            og_description=data.get("og_description"),
            og_image=_truncate(data.get("og_image"), 500),
            has_structured_data=bool(data.get("structured_data_count")),
            word_count=data.get("word_count"),
            issues=json.dumps([message for message, _ in issues], ensure_ascii=False),
        )
        environment.last_seo_checked_at = checked_at
        environment.last_seo_ok = True
        environment.last_seo_score = score
        environment.last_seo_issue_count = len(issues)
        environment.last_seo_error = None
    except Exception as exc:
        load_time_ms = round((time.monotonic() - start) * 1000)
        error_message = str(exc).splitlines()[0][:255]
        check = SeoCheck(
            checked_at=checked_at,
            ok=False,
            error=error_message,
            status_code=None,
            load_time_ms=load_time_ms,
            score=None,
        )
        _reset_seo_fields(environment, checked_at, error_message)

    environment.seo_checks.append(check)
    return check
