"""Import the FWGS store directory from OpenStreetMap (Overpass).

OSM maps Fine Wine & Good Spirits as retail POIs with addresses, ZIP, phone,
and an official ``ref`` (store number). This is a legitimate, open, machine-
readable source — much cleaner than scraping the bot-gated store locator.

County isn't in OSM tags, so we derive it from coordinates via the free FCC
Census area API. Results are written to ``data/stores.seed.csv`` and loaded.
"""
from __future__ import annotations

import csv
import logging
import time

import httpx

from .config import CACHE_DIR, get_settings
from .stores import SEED_CSV, load_stores_csv

log = logging.getLogger("paliquor.store_import")

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OVERPASS_QUERY = """
[out:json][timeout:120];
area["ISO3166-2"="US-PA"]->.pa;
(
  nwr["shop"="alcohol"]["name"~"Fine Wine",i](area.pa);
  nwr["brand"~"Fine Wine",i](area.pa);
);
out center tags;
"""
FCC_AREA = "https://geo.fcc.gov/api/census/area"
_COUNTY_CACHE = CACHE_DIR / "fcc_county.json"


_OSM_CACHE = CACHE_DIR / "osm_stores.json"


def _fetch_overpass() -> list[dict]:
    import json
    ua = get_settings().user_agent
    last_exc: Exception | None = None
    for ep in OVERPASS_ENDPOINTS:
        try:
            r = httpx.post(ep, data={"data": OVERPASS_QUERY},
                           headers={"User-Agent": ua}, timeout=130)
            r.raise_for_status()
            data = r.json()
            _OSM_CACHE.write_text(json.dumps(data))  # cache for reuse
            return data.get("elements", [])
        except Exception as exc:  # try next mirror
            last_exc = exc
            log.warning("overpass %s failed: %s", ep, exc)
    # Fall back to a previously cached Overpass result if available.
    if _OSM_CACHE.exists():
        log.warning("overpass unavailable; using cached OSM data")
        return json.loads(_OSM_CACHE.read_text()).get("elements", [])
    raise RuntimeError(f"all overpass endpoints failed: {last_exc}")


def _load_county_cache() -> dict[str, str]:
    if _COUNTY_CACHE.exists():
        import json
        return json.loads(_COUNTY_CACHE.read_text())
    return {}


def _save_county_cache(cache: dict[str, str]) -> None:
    import json
    _COUNTY_CACHE.write_text(json.dumps(cache))


def _county_for(lat: float, lon: float, cache: dict[str, str]) -> str | None:
    key = f"{lat:.5f},{lon:.5f}"
    if key in cache:
        return cache[key] or None
    try:
        r = httpx.get(FCC_AREA, params={"lat": lat, "lon": lon,
                      "censusYear": 2020, "format": "json"}, timeout=20)
        results = r.json().get("results", [])
        county = None
        for res in results:
            if res.get("state_fips") == "42":  # Pennsylvania
                name = (res.get("county_name") or "").strip()
                # FCC returns e.g. "Butler County"; our list uses "Butler".
                county = name[:-7].strip() if name.endswith(" County") else (name or None)
                break
        cache[key] = county or ""
        return county
    except Exception as exc:
        log.info("county lookup failed for %s: %s", key, exc)
        return None


def import_stores_from_osm() -> int:
    elements = _fetch_overpass()
    log.info("overpass returned %d FWGS POIs", len(elements))
    cache = _load_county_cache()

    rows: list[dict] = []
    for i, e in enumerate(elements, 1):
        t = e.get("tags", {})
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        county = _county_for(float(lat), float(lon), cache)
        if i % 25 == 0:
            _save_county_cache(cache)
            log.info("  geocoded %d/%d stores", i, len(elements))
        time.sleep(0.15)  # be gentle with the free FCC API

        ref = (t.get("ref") or "").strip()
        store_code = f"FWGS-{ref}" if ref else f"OSM-{e.get('type','n')[0]}{e.get('id')}"
        hn, street = t.get("addr:housenumber", ""), t.get("addr:street", "")
        address = " ".join(x for x in (hn, street) if x).strip()
        name = t.get("name") or "Fine Wine & Good Spirits"
        if t.get("branch"):
            name = f"{name} — {t['branch']}"
        rows.append({
            "store_code": store_code, "name": name, "county": county or "",
            "city": t.get("addr:city", ""), "address": address,
            "zip": t.get("addr:postcode", ""), "latitude": lat, "longitude": lon,
        })

    _save_county_cache(cache)

    fields = ["store_code", "name", "county", "city", "address", "zip", "latitude", "longitude"]
    with SEED_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    log.info("wrote %d stores to %s", len(rows), SEED_CSV)

    return load_stores_csv(SEED_CSV)
