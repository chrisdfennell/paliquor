"""FastAPI backend + static frontend.

Endpoints:
  GET /api/products                      list/search bourbon (UPCs, price, stock)
  GET /api/products/{code}               one product
  GET /api/products/{code}/availability  statewide + best-effort per-store
  GET /api/counties                      PA counties with store counts
  GET /api/counties/{county}/stores      stores in a county
  GET /api/meta                          catalog stats + data-source disclosure
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select

from .config import WHISKEY_CATEGORIES
from .db import init_db, session_scope
from .inventory import check_store_availability, statewide
from .models import Product, Store, Upc
from .stores import counties_with_counts, seed_stores, stores_in_county

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

app = FastAPI(title="PaLiquor — PA Bourbon Finder", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    seed_stores()


def _product_dict(p: Product) -> dict:
    return {
        "product_code": p.product_code,
        "name": p.name,
        "price": p.price,
        "size": p.size,
        "varietal": p.varietal,
        "category": p.category_label,
        "image_url": p.image_url,
        "url": p.url,
        "statewide_status": p.baseline_stock_status,
        "upcs": [u.code for u in p.upcs],
    }


@app.get("/api/meta")
def meta() -> dict:
    with session_scope() as s:
        n_products = s.scalar(select(func.count(Product.id)))
        n_upcs = s.scalar(select(func.count(Upc.id)))
    return {
        "products": n_products,
        "upcs": n_upcs,
        "categories": WHISKEY_CATEGORIES,
        "data_source": "Pennsylvania Fine Wine & Good Spirits (PLCB), public product pages",
        "disclosure": (
            "Catalog, UPCs, prices and statewide availability come from public "
            "product pages. Per-store availability is best-effort and may be "
            "limited by the source site's protections."
        ),
    }


@app.get("/api/products")
def list_products(
    q: str | None = Query(None, description="search name or UPC"),
    category: str | None = Query(None, description="category code, e.g. 152"),
    sort: str = Query("name", pattern="^(name|price_asc|price_desc)$"),
    limit: int = Query(60, le=250),
    offset: int = 0,
) -> dict:
    with session_scope() as s:
        stmt = select(Product)
        if category:
            stmt = stmt.where(Product.category_code == category)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(Product.name.ilike(like),
                    Product.upcs.any(Upc.code.ilike(like)))
            )
        total = s.scalar(select(func.count()).select_from(stmt.subquery()))
        if sort == "price_asc":
            stmt = stmt.order_by(Product.price.is_(None), Product.price.asc())
        elif sort == "price_desc":
            stmt = stmt.order_by(Product.price.desc())
        else:
            stmt = stmt.order_by(Product.name)
        rows = list(s.scalars(stmt.limit(limit).offset(offset)))
        items = [_product_dict(p) for p in rows]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/api/products/{code}")
def get_product(code: str) -> dict:
    with session_scope() as s:
        p = s.scalar(select(Product).where(Product.product_code == code))
        if not p:
            raise HTTPException(404, "product not found")
        data = _product_dict(p)
        sw = statewide(p)
        data["availability"] = {
            "statewide": {"status": sw.status, "source": sw.source,
                          "fetched_at": sw.fetched_at.isoformat() if sw.fetched_at else None},
        }
        return data


@app.get("/api/products/{code}/availability")
def availability(code: str, store_code: str | None = None) -> dict:
    with session_scope() as s:
        p = s.scalar(select(Product).where(Product.product_code == code))
        if not p:
            raise HTTPException(404, "product not found")
        store = None
        if store_code:
            store = s.scalar(select(Store).where(Store.store_code == store_code))
            if not store:
                raise HTTPException(404, "store not found")
        s.expunge(p)
        if store:
            s.expunge(store)

    sw = statewide(p)
    result = {
        "product_code": code,
        "statewide": {"status": sw.status, "source": sw.source},
    }
    if store:
        st = check_store_availability(p, store)
        result["store"] = {
            "store_code": store.store_code, "name": store.name,
            "status": st.status, "quantity": st.quantity,
            "source": st.source, "note": st.note,
            "verify_url": st.verify_url,
            "fetched_at": st.fetched_at.isoformat(),
        }
    return result


@app.get("/api/counties")
def counties() -> dict:
    return {"counties": counties_with_counts()}


@app.get("/api/counties/{county}/stores")
def county_stores(county: str) -> dict:
    rows = stores_in_county(county)
    return {
        "county": county,
        "stores": [
            {"store_code": s.store_code, "name": s.name, "city": s.city,
             "address": s.address, "zip": s.zip_code}
            for s in rows
        ],
    }


# --- static frontend (mounted last so /api/* wins) ---
@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
