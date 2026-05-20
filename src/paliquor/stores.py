"""Store directory (county -> stores).

The live FWGS store-locator API is bot-gated and the old PLCB lookup host is
gone, so the directory is *pluggable*: load the official PLCB store export
(CSV) when you have one. We ship PA's 67 counties as the navigation backbone
and a small set of real example stores so the by-county UI works out of the box.

CSV columns (header row, case-insensitive): store_code, name, county, city,
address, zip, latitude, longitude. Only store_code + county are required.
"""
from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import select

from .config import DATA_DIR
from .db import session_scope
from .models import Store

# Pennsylvania's 67 counties — factual, used as the navigation backbone.
PA_COUNTIES = [
    "Adams", "Allegheny", "Armstrong", "Beaver", "Bedford", "Berks", "Blair",
    "Bradford", "Bucks", "Butler", "Cambria", "Cameron", "Carbon", "Centre",
    "Chester", "Clarion", "Clearfield", "Clinton", "Columbia", "Crawford",
    "Cumberland", "Dauphin", "Delaware", "Elk", "Erie", "Fayette", "Forest",
    "Franklin", "Fulton", "Greene", "Huntingdon", "Indiana", "Jefferson",
    "Juniata", "Lackawanna", "Lancaster", "Lawrence", "Lebanon", "Lehigh",
    "Luzerne", "Lycoming", "McKean", "Mercer", "Mifflin", "Monroe",
    "Montgomery", "Montour", "Northampton", "Northumberland", "Perry",
    "Philadelphia", "Pike", "Potter", "Schuylkill", "Snyder", "Somerset",
    "Sullivan", "Susquehanna", "Tioga", "Union", "Venango", "Warren",
    "Washington", "Wayne", "Westmoreland", "Wyoming", "York",
]

SEED_CSV = DATA_DIR / "stores.seed.csv"


def load_stores_csv(path: Path) -> int:
    """Upsert stores from a CSV export. Returns the number processed."""
    n = 0
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        norm = {f.lower(): f for f in (reader.fieldnames or [])}
        with session_scope() as session:
            for row in reader:
                def g(key: str) -> str | None:
                    col = norm.get(key)
                    val = (row.get(col) or "").strip() if col else ""
                    return val or None

                code = g("store_code")
                if not code:
                    continue
                store = session.scalar(select(Store).where(Store.store_code == code))
                if store is None:
                    store = Store(store_code=code)
                    session.add(store)
                store.name = g("name") or store.name
                store.county = g("county") or store.county
                store.city = g("city") or store.city
                store.address = g("address") or store.address
                store.zip_code = g("zip") or store.zip_code
                try:
                    store.latitude = float(g("latitude")) if g("latitude") else store.latitude
                    store.longitude = float(g("longitude")) if g("longitude") else store.longitude
                except ValueError:
                    pass
                n += 1
    return n


def clear_stores() -> int:
    """Delete all stores (and their cached inventory). Returns rows removed."""
    from .models import InventoryCache
    with session_scope() as session:
        n = session.query(Store).count()
        session.query(InventoryCache).delete()
        session.query(Store).delete()
    return n


def seed_stores() -> int:
    """Load the bundled seed CSV if present; otherwise no-op."""
    if SEED_CSV.exists():
        return load_stores_csv(SEED_CSV)
    return 0


def counties_with_counts() -> list[dict]:
    """Every PA county with how many stores we currently know about."""
    with session_scope() as session:
        rows = session.execute(
            select(Store.county, Store.id).where(Store.county.is_not(None))
        ).all()
    counts: dict[str, int] = {}
    for county, _ in rows:
        counts[county] = counts.get(county, 0) + 1
    return [{"county": c, "store_count": counts.get(c, 0)} for c in PA_COUNTIES]


def stores_in_county(county: str) -> list[Store]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(Store).where(Store.county == county).order_by(Store.city, Store.name)
            )
        )
