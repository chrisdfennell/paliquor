"""Discover product codes within a category, via the real browser.

The category listing paginates through the gated API, so a plain HTTP fetch
only sees the first page. A real Chromium runs the site's JS, clears Akamai
naturally, and renders the full list — we then read product codes from the DOM.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from playwright.sync_api import BrowserContext, TimeoutError as PWTimeout

from .browser import HUMAN_PAUSE_MS, browser_context
from .config import WHISKEY_CATEGORIES

_CODE_RE = re.compile(r"/product/(\d{6,12})")
# Buttons that reveal more results, in rough order of likelihood.
_MORE_SELECTORS = [
    "button:has-text('Load More')",
    "button:has-text('Show More')",
    "a:has-text('Load More')",
    "[class*='load-more'] button",
    "[class*='loadMore']",
]


@dataclass
class CategoryItem:
    product_code: str
    url: str


def _harvest_codes(page) -> dict[str, str]:
    """Map product_code -> absolute url from all product anchors on the page."""
    found: dict[str, str] = {}
    for a in page.query_selector_all("a[href*='/product/']"):
        href = a.get_attribute("href") or ""
        m = _CODE_RE.search(href)
        if m:
            code = m.group(1).zfill(9)
            if href.startswith("/"):
                href = "https://www.finewineandgoodspirits.com" + href
            found.setdefault(code, href)
    return found


def enumerate_category(
    category_code: str, context: BrowserContext, max_rounds: int = 60
) -> list[CategoryItem]:
    page = context.new_page()
    items: dict[str, str] = {}
    try:
        page.goto(f"/{_slug(category_code)}/{category_code}", wait_until="domcontentloaded")
        try:
            page.wait_for_selector("a[href*='/product/']", timeout=30_000)
        except PWTimeout:
            return []

        stagnant = 0
        for _ in range(max_rounds):
            before = len(items)
            items.update(_harvest_codes(page))

            # Try an explicit "load more" control; otherwise fall back to scroll.
            clicked = False
            for sel in _MORE_SELECTORS:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    try:
                        btn.click()
                        clicked = True
                        break
                    except Exception:
                        pass
            if not clicked:
                page.mouse.wheel(0, 20_000)

            page.wait_for_timeout(HUMAN_PAUSE_MS)
            items.update(_harvest_codes(page))

            stagnant = stagnant + 1 if len(items) == before else 0
            if stagnant >= 3:  # nothing new for several rounds -> done
                break
    finally:
        page.close()

    return [CategoryItem(code, url) for code, url in sorted(items.items())]


def _slug(category_code: str) -> str:
    label = WHISKEY_CATEGORIES.get(category_code, "category")
    return label.lower().replace(" ", "-")


def enumerate_categories(category_codes: list[str]) -> dict[str, list[CategoryItem]]:
    """Enumerate several categories in one browser session."""
    result: dict[str, list[CategoryItem]] = {}
    with browser_context() as context:
        for code in category_codes:
            result[code] = enumerate_category(code, context)
            time.sleep(1.0)  # gentle gap between categories
    return result
