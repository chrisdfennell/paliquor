"""Availability lookups.

Two tiers, honestly labelled:

* ``statewide``  — the orderable/stock figure embedded in the public product
  page (``stockStatus`` / ``orderableQuantity``, ``locationId: null``). Always
  available, cheap, legitimate.

* ``store`` (best-effort) — a single, on-demand live check for one product at
  one store, run through a real browser. Per-store availability is gated by the
  site's bot protection, so this may return ``unavailable`` (blocked) rather
  than a number. We never bulk-harvest it; it runs only when a user asks, and
  the result is cached for ``INVENTORY_TTL_HOURS``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .config import get_settings
from .db import session_scope
from .models import InventoryCache, Product, Store

log = logging.getLogger("paliquor.inventory")


@dataclass
class AvailabilityResult:
    scope: str            # "statewide" | "store"
    status: str           # IN_STOCK | OUT_OF_STOCK | UNKNOWN | UNAVAILABLE
    quantity: int | None
    source: str           # human-readable provenance
    fetched_at: datetime
    note: str | None = None
    verify_url: str | None = None  # official page to confirm at this store


def statewide(product: Product) -> AvailabilityResult:
    return AvailabilityResult(
        scope="statewide",
        status=product.baseline_stock_status or "UNKNOWN",
        quantity=None,
        source="product page (statewide orderable status)",
        fetched_at=product.last_seen,
    )


def _fresh_cache(product_id: int, store_id: int) -> InventoryCache | None:
    ttl = timedelta(hours=get_settings().inventory_ttl_hours)
    with session_scope() as session:
        row = session.scalar(
            select(InventoryCache).where(
                InventoryCache.product_id == product_id,
                InventoryCache.store_id == store_id,
            )
        )
        if row and datetime.now(timezone.utc) - row.fetched_at < ttl:
            session.expunge(row)
            return row
    return None


def _store_url(slug_or_url: str) -> str:
    return slug_or_url


def check_store_availability(product: Product, store: Store) -> AvailabilityResult:
    """Best-effort, cached, single live check of one product at one store.

    Returns UNAVAILABLE (not an error) when the gated store flow can't be read.
    """
    verify_url = product.url
    cached = _fresh_cache(product.id, store.id)
    if cached:
        return AvailabilityResult(
            scope="store", status=cached.status or "UNKNOWN", quantity=cached.quantity,
            source=f"cached ({store.name or store.store_code})", fetched_at=cached.fetched_at,
            verify_url=verify_url,
        )

    status, qty, note = _probe_store(product, store)

    with session_scope() as session:
        row = session.scalar(
            select(InventoryCache).where(
                InventoryCache.product_id == product.id,
                InventoryCache.store_id == store.id,
            )
        )
        if row is None:
            row = InventoryCache(product_id=product.id, store_id=store.id)
            session.add(row)
        row.status = status
        row.quantity = qty
        row.fetched_at = datetime.now(timezone.utc)

    return AvailabilityResult(
        scope="store", status=status, quantity=qty,
        source=f"live check ({store.name or store.store_code})",
        fetched_at=datetime.now(timezone.utc), note=note, verify_url=verify_url,
    )


def _probe_store(product: Product, store: Store) -> tuple[str, int | None, str | None]:
    """Attempt a single browser-based per-store read. Degrades gracefully.

    Imported lazily so the API/catalog don't require Playwright to be present.
    """
    try:
        from .browser import browser_context  # noqa: WPS433 (lazy import by design)
    except Exception as exc:  # Playwright not installed
        return "UNAVAILABLE", None, f"browser unavailable: {exc}"

    try:
        with browser_context() as ctx:
            page = ctx.new_page()
            page.goto(product.url, wait_until="domcontentloaded")
            page.wait_for_timeout(6000)
            # Best-effort: read any rendered per-store availability text.
            text = page.inner_text("body").lower()
            page.close()
            if store.city and store.city.lower() in text and "in stock" in text:
                return "IN_STOCK", None, "matched store context on page"
            return "UNKNOWN", None, (
                "per-store stock is gated by the site's bot protection; "
                "showing statewide status instead"
            )
    except Exception as exc:
        log.info("store probe degraded for %s @ %s: %s", product.product_code, store.store_code, exc)
        return "UNAVAILABLE", None, "live per-store check was blocked or timed out"
