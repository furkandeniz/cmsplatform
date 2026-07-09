import uuid
from pathlib import Path
from typing import List, Tuple
from urllib.parse import urlparse, urlunparse

import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

from app.models import ComparisonPage, EnvironmentComparison

STATIC_DIR = Path("app/static")
UPLOAD_DIR = STATIC_DIR / "uploads" / "comparisons"

DIFF_BLOCK_SIZE = 32
DIFF_PIXEL_THRESHOLD = 30
DIFF_BLOCK_RATIO = 0.08
DIFF_FRAME_COLOR = (239, 68, 68)
DIFF_FRAME_WIDTH = 3
SCREENSHOT_TIMEOUT_MS = 20000


def _find_diff_regions(block_diff: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Groups adjacent differing blocks (8-connectivity) into bounding boxes,
    expressed as (min_row, min_col, max_row, max_col) block indices."""
    rows, cols = block_diff.shape
    visited = np.zeros_like(block_diff, dtype=bool)
    regions = []

    for start_row in range(rows):
        for start_col in range(cols):
            if not block_diff[start_row, start_col] or visited[start_row, start_col]:
                continue

            stack = [(start_row, start_col)]
            visited[start_row, start_col] = True
            min_row = max_row = start_row
            min_col = max_col = start_col

            while stack:
                row, col = stack.pop()
                min_row, max_row = min(min_row, row), max(max_row, row)
                min_col, max_col = min(min_col, col), max(max_col, col)
                for delta_row in (-1, 0, 1):
                    for delta_col in (-1, 0, 1):
                        next_row, next_col = row + delta_row, col + delta_col
                        if (
                            0 <= next_row < rows
                            and 0 <= next_col < cols
                            and block_diff[next_row, next_col]
                            and not visited[next_row, next_col]
                        ):
                            visited[next_row, next_col] = True
                            stack.append((next_row, next_col))

            regions.append((min_row, min_col, max_row, max_col))

    return regions


def _build_url(base_url: str, path: str) -> str:
    """Combines the environment's domain with an absolute path, ignoring any
    existing path segment on base_url (so a "/mobile" step always means
    "https://domain/mobile", not "https://domain/existing-path/mobile")."""
    parsed_base = urlparse(base_url)
    normalized_path = "/" + (path or "").strip().lstrip("/")
    return urlunparse((parsed_base.scheme, parsed_base.netloc, normalized_path, "", "", ""))


def _screenshot(page, url: str, output_path: Path) -> None:
    page.goto(url, wait_until="load", timeout=SCREENSHOT_TIMEOUT_MS)
    page.screenshot(path=str(output_path), full_page=True)


def _compute_diff(image_a_path: Path, image_b_path: Path, diff_output_path: Path) -> Tuple[float, bool]:
    image_a = Image.open(image_a_path).convert("RGB")
    image_b = Image.open(image_b_path).convert("RGB")

    width = max(image_a.width, image_b.width)
    height = max(image_a.height, image_b.height)

    canvas_a = Image.new("RGB", (width, height), "white")
    canvas_a.paste(image_a, (0, 0))
    canvas_b = Image.new("RGB", (width, height), "white")
    canvas_b.paste(image_b, (0, 0))

    array_a = np.asarray(canvas_a, dtype=np.int16)
    array_b = np.asarray(canvas_b, dtype=np.int16)

    pixel_diff = np.abs(array_a - array_b).sum(axis=2)
    diff_mask = pixel_diff > DIFF_PIXEL_THRESHOLD

    total_pixels = width * height
    diff_pixels = int(diff_mask.sum())
    diff_percentage = round((diff_pixels / total_pixels) * 100, 2) if total_pixels else 0.0

    block_cols = -(-width // DIFF_BLOCK_SIZE)
    block_rows = -(-height // DIFF_BLOCK_SIZE)
    block_diff = np.zeros((block_rows, block_cols), dtype=bool)
    for block_row in range(block_rows):
        for block_col in range(block_cols):
            y0, y1 = block_row * DIFF_BLOCK_SIZE, min((block_row + 1) * DIFF_BLOCK_SIZE, height)
            x0, x1 = block_col * DIFF_BLOCK_SIZE, min((block_col + 1) * DIFF_BLOCK_SIZE, width)
            block = diff_mask[y0:y1, x0:x1]
            if block.size and (block.sum() / block.size) > DIFF_BLOCK_RATIO:
                block_diff[block_row, block_col] = True

    regions = _find_diff_regions(block_diff)
    has_differences = len(regions) > 0

    annotated = canvas_b.copy()
    draw = ImageDraw.Draw(annotated)
    for min_row, min_col, max_row, max_col in regions:
        x0 = min_col * DIFF_BLOCK_SIZE
        y0 = min_row * DIFF_BLOCK_SIZE
        x1 = min((max_col + 1) * DIFF_BLOCK_SIZE, width) - 1
        y1 = min((max_row + 1) * DIFF_BLOCK_SIZE, height) - 1
        draw.rectangle([x0, y0, x1, y1], outline=DIFF_FRAME_COLOR, width=DIFF_FRAME_WIDTH)

    annotated.save(diff_output_path)
    return diff_percentage, has_differences


def run_comparison(comparison: EnvironmentComparison, paths: List[str]) -> None:
    comparison_dir = UPLOAD_DIR / str(comparison.id)
    comparison_dir.mkdir(parents=True, exist_ok=True)

    url_a_base = comparison.environment_a.url
    url_b_base = comparison.environment_b.url

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            for path in paths:
                comparison_page = ComparisonPage(comparison_id=comparison.id, path=path)
                comparison.pages.append(comparison_page)

                token = uuid.uuid4().hex
                screenshot_a = comparison_dir / f"{token}_a.png"
                screenshot_b = comparison_dir / f"{token}_b.png"
                diff_image = comparison_dir / f"{token}_diff.png"

                try:
                    _screenshot(page, _build_url(url_a_base, path), screenshot_a)
                    _screenshot(page, _build_url(url_b_base, path), screenshot_b)
                    diff_percentage, has_differences = _compute_diff(screenshot_a, screenshot_b, diff_image)

                    comparison_page.ok = True
                    comparison_page.error = None
                    comparison_page.screenshot_a_path = str(screenshot_a.relative_to(STATIC_DIR))
                    comparison_page.screenshot_b_path = str(screenshot_b.relative_to(STATIC_DIR))
                    comparison_page.diff_image_path = str(diff_image.relative_to(STATIC_DIR))
                    comparison_page.diff_percentage = diff_percentage
                    comparison_page.has_differences = has_differences
                except Exception as exc:
                    comparison_page.ok = False
                    comparison_page.error = str(exc).splitlines()[0][:255]
        finally:
            browser.close()
