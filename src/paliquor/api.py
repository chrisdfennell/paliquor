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

from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select

from .config import WHISKEY_CATEGORIES
from .db import init_db, session_scope
from .inventory import check_store_availability, statewide
from .models import PriceSnapshot, Product, Store, Upc, Watch
from .stores import counties_with_counts, seed_stores, stores_in_county

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

app = FastAPI(title="PaLiquor — PA Bourbon Finder", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    seed_stores()


def _product_dict(p: Product) -> dict:
    on_sale = bool(p.sale_price and p.list_price and p.sale_price < p.list_price)
    return {
        "product_code": p.product_code,
        "name": p.name,
        "price": p.price,
        "list_price": p.list_price,
        "sale_price": p.sale_price,
        "on_sale": on_sale,
        "savings": round(p.list_price - p.sale_price, 2) if on_sale else None,
        "discount_pct": round(100 * (p.list_price - p.sale_price) / p.list_price) if on_sale else None,
        "is_chairmans": p.is_chairmans,
        "proof": p.proof,
        "size": p.size,
        "volume_ml": p.volume_ml,
        "price_per_750": p.price_per_750,
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


def _sort_clauses(sort: str) -> list:
    """Map a sort key to ORDER BY clauses. NULLs in the sort column sink last."""
    P = Product
    value = P.price * 750.0 / P.volume_ml             # $/750 mL (lower = better value)
    savings = P.list_price - P.price                  # $ off
    discount = (P.list_price - P.price) / P.list_price  # fraction off
    options: dict[str, list] = {
        "name":          [P.name.asc()],
        "name_desc":     [P.name.desc()],
        "price_asc":     [P.price.is_(None), P.price.asc()],
        "price_desc":    [P.price.is_(None), P.price.desc()],
        "value":         [P.volume_ml.is_(None), value.asc()],   # best value first
        "value_desc":    [P.volume_ml.is_(None), value.desc()],  # most premium per mL
        "proof_desc":    [P.proof.is_(None), P.proof.desc()],
        "proof_asc":     [P.proof.is_(None), P.proof.asc()],
        "discount_desc": [discount.is_(None), discount.desc()],  # biggest % off
        "savings_desc":  [savings.is_(None), savings.desc()],    # biggest $ off
        "size_desc":     [P.volume_ml.is_(None), P.volume_ml.desc()],  # largest bottle
        "size_asc":      [P.volume_ml.is_(None), P.volume_ml.asc()],
    }
    return options.get(sort, options["name"])


SORT_KEYS = (
    "name|name_desc|price_asc|price_desc|value|value_desc|"
    "proof_desc|proof_asc|discount_desc|savings_desc|size_desc|size_asc"
)


@app.get("/api/products")
def list_products(
    q: str | None = Query(None, description="search name or UPC"),
    category: str | None = Query(None, description="category code, e.g. 152"),
    sort: str = Query("name", pattern=f"^({SORT_KEYS})$"),
    chairmans: bool = Query(False, description="only Chairman's Selection"),
    on_sale: bool = Query(False, description="only discounted items"),
    limit: int = Query(60, le=250),
    offset: int = 0,
) -> dict:
    with session_scope() as s:
        stmt = select(Product)
        if category:
            stmt = stmt.where(Product.category_code == category)
        if chairmans:
            stmt = stmt.where(Product.is_chairmans.is_(True))
        if on_sale:
            stmt = stmt.where(Product.sale_price.is_not(None),
                              Product.sale_price < Product.list_price)
        if q:
            like = f"%{q}%"
            # apostrophe-insensitive: strip ' from BOTH the name and the query so
            # "makers" matches "Maker's".
            stripped = f"%{q.replace(chr(39), '')}%"
            name_no_apos = func.replace(Product.name, "'", "")
            stmt = stmt.where(
                or_(Product.name.ilike(like),
                    name_no_apos.ilike(stripped),
                    Product.upcs.any(Upc.code.ilike(like)))
            )
        total = s.scalar(select(func.count()).select_from(stmt.subquery()))
        stmt = stmt.order_by(*_sort_clauses(sort))
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


@app.get("/api/products/{code}/history")
def price_history(code: str, limit: int = Query(180, le=1000)) -> dict:
    with session_scope() as s:
        p = s.scalar(select(Product).where(Product.product_code == code))
        if not p:
            raise HTTPException(404, "product not found")
        rows = list(s.scalars(
            select(PriceSnapshot)
            .where(PriceSnapshot.product_id == p.id)
            .order_by(PriceSnapshot.captured_at.asc())
            .limit(limit)
        ))
        return {
            "product_code": code,
            "history": [
                {"price": r.price, "status": r.stock_status,
                 "at": r.captured_at.isoformat()}
                for r in rows
            ],
        }


class WatchIn(BaseModel):
    email: str
    target_price: float | None = None


@app.post("/api/products/{code}/watch")
def add_watch(code: str, body: WatchIn) -> dict:
    if "@" not in body.email or "." not in body.email.split("@")[-1]:
        raise HTTPException(422, "invalid email")
    with session_scope() as s:
        p = s.scalar(select(Product).where(Product.product_code == code))
        if not p:
            raise HTTPException(404, "product not found")
        existing = s.scalar(select(Watch).where(
            Watch.email == body.email, Watch.product_id == p.id))
        if existing:
            existing.target_price = body.target_price
            created = False
        else:
            # Seed last_* with the current state so we alert only on the next change.
            s.add(Watch(email=body.email, product_id=p.id,
                        target_price=body.target_price,
                        last_status=p.baseline_stock_status, last_price=p.price))
            created = True
    return {"watching": code, "email": body.email,
            "target_price": body.target_price, "created": created}


@app.delete("/api/products/{code}/watch")
def remove_watch(code: str, email: str) -> dict:
    with session_scope() as s:
        p = s.scalar(select(Product).where(Product.product_code == code))
        if not p:
            raise HTTPException(404, "product not found")
        w = s.scalar(select(Watch).where(Watch.email == email, Watch.product_id == p.id))
        if w:
            s.delete(w)
    return {"unwatched": code, "email": email}


@app.get("/api/watches")
def list_watches(email: str) -> dict:
    with session_scope() as s:
        rows = s.execute(
            select(Watch, Product).join(Product, Watch.product_id == Product.id)
            .where(Watch.email == email)
        ).all()
        return {"email": email, "watches": [
            {**_product_dict(p), "target_price": w.target_price} for w, p in rows
        ]}


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
