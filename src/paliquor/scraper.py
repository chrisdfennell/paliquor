"""Catalog refresh: discover SKUs (browser) then parse each product (HTTP).

Enumeration uses a real browser once per run; per-product detail uses the cheap,
throttled HTTP client. Both honor caching, so re-runs are inexpensive.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from .catalog import fetch_product
from .config import WHISKEY_CATEGORIES, get_settings
from .db import session_scope
from .enumerate import enumerate_categories
from .http_client import client
from .models import PriceSnapshot, Product, Upc

log = logging.getLogger("paliquor.scraper")


def _record_snapshot(session, product: Product) -> None:
    """Append a snapshot only when price or stock changed since the last one."""
    latest = session.scalar(
        select(PriceSnapshot)
        .where(PriceSnapshot.product_id == product.id)
        .order_by(PriceSnapshot.captured_at.desc())
    )
    if (latest is None
            or latest.price != product.price
            or latest.stock_status != product.baseline_stock_status):
        session.add(PriceSnapshot(
            product_id=product.id, price=product.price,
            stock_status=product.baseline_stock_status,
        ))


def _upsert_product(session, parsed, category_code: str) -> None:
    product = session.scalar(
        select(Product).where(Product.product_code == parsed.product_code)
    )
    if product is None:
        product = Product(product_code=parsed.product_code)
        session.add(product)

    product.name = parsed.name or product.name
    product.url = parsed.url or product.url
    product.price = parsed.price
    product.list_price = parsed.list_price
    product.sale_price = parsed.sale_price
    product.is_chairmans = parsed.is_chairmans
    product.proof = parsed.proof
    product.volume_ml = parsed.volume_ml
    product.image_url = parsed.image_url
    product.varietal = parsed.varietal
    product.size = parsed.size
    product.baseline_stock_status = parsed.baseline_stock_status
    product.category_code = category_code
    product.category_label = WHISKEY_CATEGORIES.get(category_code)
    session.flush()

    _record_snapshot(session, product)

    existing = {u.code for u in product.upcs}
    for code in parsed.upcs:
        if code not in existing:
            session.add(Upc(product_id=product.id, code=code))


def refresh_catalog(category_codes: list[str], limit: int | None = None) -> dict[str, int]:
    """Enumerate the given categories and refresh product detail for each SKU."""
    discovered = enumerate_categories(category_codes)
    stats = {"discovered": 0, "parsed": 0, "errors": 0}

    for category_code, found in discovered.items():
        items = found[:limit] if limit else found
        stats["discovered"] += len(items)
        log.info("category %s (%s): %d products",
                 category_code, WHISKEY_CATEGORIES.get(category_code), len(items))
        for item in items:
            try:
                parsed = fetch_product(item.product_code, url=item.url)
                with session_scope() as session:
                    _upsert_product(session, parsed, category_code)
                stats["parsed"] += 1
            except Exception as exc:  # keep going; one bad page shouldn't abort
                stats["errors"] += 1
                log.warning("failed %s: %s", item.product_code, exc)

    client().close()

    # After refreshing the catalog, fire any restock / price-drop alerts.
    try:
        from .alerts import evaluate_watches
        stats["alerts"] = evaluate_watches()
    except Exception as exc:  # alerts must never break a refresh
        log.warning("alert evaluation failed: %s", exc)

    return stats
