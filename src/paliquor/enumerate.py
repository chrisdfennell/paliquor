"""Discover product codes within a category — via plain, polite HTTP.

The category page is server-rendered and honors Oracle Commerce pagination
params on the *public* URL:
  * ``Nrpp`` — results per page (caps at 250)
  * ``Ns``   — sort key, e.g. ``sku.activePrice|0`` (asc) / ``|1`` (desc)

Since a category of <= 500 items is fully covered by "cheapest 250" ∪
"priciest 250", two requests enumerate the whole category. This needs no
JavaScript and never trips the site's bot protection — we just ask the public
page for more rows, the same way its own sort/paging controls do.

For categories larger than 500, we add more sort axes (name asc/desc) to widen
coverage; we log if the union still falls short of the reported total.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import BASE_URL, WHISKEY_CATEGORIES
from .http_client import client

_CODE_RE = re.compile(r"/product/(\d{6,12})")
_TOTAL_RE = re.compile(r"of\s+([\d,]+)\s+results", re.I)
_MAX_RPP = 250

# Sort axes used to widen coverage, in order. Each is an Ns value.
_SORT_AXES = [
    "sku.activePrice|0",   # price ascending  (cheapest first)
    "sku.activePrice|1",   # price descending (priciest first)
    "product.displayName|0",
    "product.displayName|1",
]


@dataclass
class CategoryItem:
    product_code: str
    url: str


def _slug(category_code: str) -> str:
    return WHISKEY_CATEGORIES.get(category_code, "category").lower().replace(" ", "-")


def _page_url(category_code: str, sort: str | None) -> str:
    url = f"{BASE_URL}/{_slug(category_code)}/{category_code}?Nrpp={_MAX_RPP}"
    if sort:
        url += "&Ns=" + sort.replace("|", "%7C")
    return url


def _harvest(html: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for m in re.finditer(r'(?:href="|/)([a-z0-9%-]+/product/(\d{6,12}))', html):
        slug_path, code = m.group(1), m.group(2)
        found.setdefault(code.zfill(9), f"{BASE_URL}/{slug_path}")
    return found


def _reported_total(html: str) -> int | None:
    m = _TOTAL_RE.search(html)
    return int(m.group(1).replace(",", "")) if m else None


def enumerate_category(category_code: str) -> list[CategoryItem]:
    items: dict[str, str] = {}
    total: int | None = None

    for sort in _SORT_AXES:
        html = client().get(_page_url(category_code, sort))
        total = total or _reported_total(html)
        items.update(_harvest(html))
        # Stop early once we've covered everything the site reports.
        if total and len(items) >= total:
            break

    if total and len(items) < total:
        import logging
        logging.getLogger("paliquor.enumerate").warning(
            "category %s: found %d of %d reported; add sort axes for full coverage",
            category_code, len(items), total,
        )
    return [CategoryItem(c, u) for c, u in sorted(items.items())]


def enumerate_categories(category_codes: list[str]) -> dict[str, list[CategoryItem]]:
    return {code: enumerate_category(code) for code in category_codes}
