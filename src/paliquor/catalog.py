"""Parse a public product page into structured catalog data.

Two complementary sources inside the same 200-OK HTML:
  * schema.org ``Product`` JSON-LD  -> name, sku, price, availability, image
  * the page's URL-encoded app state -> UPC(s), varietal, size, stock status

Neither requires the Akamai-gated API. We only read what the site already
serves to any browser.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import unquote

from selectolax.parser import HTMLParser

from .config import BASE_URL
from .http_client import client

PRODUCT_URL = BASE_URL + "/x/product/{code}"  # slug is cosmetic; "x" works as placeholder

# Keys we pull out of the decoded app-state blob.
_STATE_FIELDS = {
    "upc_raw": r'"b2c_upc"\s*:\s*"([^"]*)"',
    "varietal": r'"b2c_varietal"\s*:\s*"([^"]*)"',
    "size": r'"b2c_size"\s*:\s*"([^"]*)"',
    "stock_status": r'"stockStatus"\s*:\s*"([^"]*)"',
    "chairmans": r'"b2c_chairmansSelection"\s*:\s*"([^"]*)"',
    "proof": r'"b2c_proof"\s*:\s*"?([0-9.]+)"?',
    "list_price": r'"listPrice"\s*:\s*([0-9.]+)',
    "sale_price": r'"salePrice"\s*:\s*([0-9.]+)',
}


@dataclass
class ParsedProduct:
    product_code: str
    name: str | None = None
    url: str | None = None
    price: float | None = None
    list_price: float | None = None
    sale_price: float | None = None
    is_chairmans: bool = False
    proof: float | None = None
    volume_ml: float | None = None
    image_url: str | None = None
    varietal: str | None = None
    size: str | None = None
    baseline_stock_status: str | None = None
    upcs: list[str] = field(default_factory=list)


def _to_float(val: str | None) -> float | None:
    try:
        return float(val) if val not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _volume_ml(size: str | None) -> float | None:
    """Parse '750ML', '1.75L', '1L', '50ML' -> milliliters."""
    if not size:
        return None
    m = re.search(r"([0-9.]+)\s*(ML|L)\b", size, re.I)
    if not m:
        return None
    qty = float(m.group(1))
    return qty * 1000.0 if m.group(2).upper() == "L" else qty


def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1).strip() if m and m.group(1).strip() else None


def _parse_jsonld(tree: HTMLParser) -> dict:
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text())
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "Product":
                return item
    return {}


def parse_product(html: str, product_code: str, url: str | None = None) -> ParsedProduct:
    tree = HTMLParser(html)
    ld = _parse_jsonld(tree)

    price = None
    offers = ld.get("offers")
    if isinstance(offers, dict):
        try:
            price = float(offers.get("price"))
        except (TypeError, ValueError):
            price = None

    # The app state is URL-encoded JSON; decode the whole page then regex it.
    decoded = unquote(html)
    state = {key: _first(pat, decoded) for key, pat in _STATE_FIELDS.items()}

    upcs: list[str] = []
    if state.get("upc_raw"):
        # Field may hold several space-separated UPCs.
        upcs = [u for u in re.split(r"\s+", state["upc_raw"]) if u.isdigit()]

    list_price = _to_float(state.get("list_price"))
    sale_price = _to_float(state.get("sale_price"))
    # JSON-LD price is the active price; fall back to sale/list if missing.
    if price is None:
        price = sale_price or list_price

    return ParsedProduct(
        product_code=product_code,
        name=ld.get("name"),
        url=url or ld.get("@id"),
        price=price,
        list_price=list_price,
        sale_price=sale_price,
        is_chairmans=(state.get("chairmans") or "").upper() == "Y",
        proof=_to_float(state.get("proof")),
        volume_ml=_volume_ml(state.get("size")),
        image_url=ld.get("image"),
        varietal=state.get("varietal"),
        size=state.get("size"),
        baseline_stock_status=state.get("stock_status"),
        upcs=upcs,
    )


def fetch_product(product_code: str, url: str | None = None) -> ParsedProduct:
    """Fetch and parse a single product by its zero-padded code."""
    target = url or PRODUCT_URL.format(code=product_code)
    html = client().get(target)
    return parse_product(html, product_code, url=target)
