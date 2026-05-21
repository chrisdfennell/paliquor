# PaLiquor — Pennsylvania Bourbon & Whiskey Finder

Browse Pennsylvania (Fine Wine & Good Spirits / PLCB) **bourbon & whiskey** by
name, UPC, price, and by county/store. Built with Python + FastAPI + SQLite and
a small vanilla-JS frontend.

- **Catalog**: every bourbon (494) and the whiskey siblings — names, **UPCs**,
  prices, sizes, and statewide availability.
- **Store directory**: stores grouped by county, with the ability to load the
  official PLCB store list.
- **Availability**: statewide stock status, plus a best-effort per-store check.

## How data is sourced (and what's deliberately *not* done)

Everything comes from public, legitimate sources. This project is a **polite,
honest client** — it does **not** evade bot protection.

| Data | Source | Method |
|------|--------|--------|
| Product catalog (UPCs, price, size, statewide stock) | public product pages on `finewineandgoodspirits.com` | schema.org `Product` JSON-LD + the page's embedded app-state; throttled HTTP, cached |
| SKU discovery by category | the category pages (server-rendered) | Oracle Commerce pagination params (`Nrpp=250` + a price sort ascending/descending); the union of "cheapest 250" + "priciest 250" covers a category ≤ 500 in **two requests, no browser** |
| Store directory | OpenStreetMap (Overpass) + FCC Census geo for counties | one query; counties derived from coordinates |
| Store directory (authoritative) | official PLCB store list | CSV import (`import-stores-csv`) |
| Per-store availability | best-effort live read via a real browser | on demand only, cached |

### What's gated, and why we stop there

The site's `/ccstore/v1/` JSON API and all JS-driven interactions (category
"Load More", the store-locator search, true per-store inventory) sit behind
**Akamai bot management** — they return 403 / silently fail even for a real
*headless* browser. We deliberately do **not**:

- forge Akamai sensor tokens / `_abck` cookies,
- stealth-patch the browser to hide automation, or
- rotate proxies to dodge bans.

Consequences, stated honestly:

- **Per-store shelf inventory** isn't publicly available in bulk. The public
  data is **statewide** availability (`stockStatus`, `locationId: null`). The
  per-store "check" is best-effort and usually degrades to the statewide signal
  plus a link to confirm on the official site.
- **The complete store list** isn't a clean public dataset. OSM gives ~345
  stores (incomplete in some counties); load the official PLCB list for full
  coverage — see **[STORES.md](STORES.md)**.

### Operating principles

- Honest, self-identifying `User-Agent` including a contact address.
- Honors `robots.txt` (notably: never touches `/searchresults`).
- Conservative request rate (default 2s) with on-disk caching and incremental
  updates.

> Before running publicly, review the FWGS Terms of Use. This is an independent
> informational tool for personal price/availability lookup — not affiliated
> with or endorsed by the PLCB.

## Layout

```
src/paliquor/
  config.py        # settings: rate limit, user-agent + contact, TTLs, categories
  http_client.py   # polite throttled + cached HTTP client (catalog fetches)
  models.py        # SQLAlchemy models (products, upcs, stores, inventory cache)
  db.py            # engine / session helpers
  enumerate.py     # discover SKUs by category via HTTP sort-union (no browser)
  catalog.py       # parse a product page -> UPCs, price, size, stock
  scraper.py       # orchestrate: enumerate -> parse -> upsert
  stores.py        # store directory: PA counties, CSV loader
  store_import.py  # import stores from OpenStreetMap + FCC county lookup
  browser.py       # shared Playwright context (best-effort per-store check only)
  inventory.py     # statewide signal + best-effort, cached per-store check
  api.py           # FastAPI app (JSON API + serves the web UI)
  cli.py           # command-line entrypoints
web/               # static frontend (index.html, styles.css, app.js)
data/              # sqlite db, http/osm/geo cache, seed CSVs (db+cache gitignored)
```

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
playwright install chromium      # only needed for the best-effort per-store check

copy .env.example .env           # then set CONTACT_EMAIL so requests identify honestly

python -m paliquor.cli init-db
python -m paliquor.cli refresh-catalog        # bourbon (default)
python -m paliquor.cli import-stores          # store directory from OpenStreetMap
uvicorn paliquor.api:app --reload             # serve API + frontend at http://127.0.0.1:8000
```

## CLI reference

```powershell
# Catalog
python -m paliquor.cli refresh-catalog                       # bourbon (152)
python -m paliquor.cli refresh-catalog --categories 152,156,153,157,159,158,160,161,162
python -m paliquor.cli refresh-catalog --limit 50            # cap per category (testing)

# Stores
python -m paliquor.cli import-stores                         # from OpenStreetMap (free, partial)
python -m paliquor.cli import-stores-csv stores.csv --replace # official PLCB list (see STORES.md)

# Alerts (restock / price-drop on watched bottles)
python -m paliquor.cli check-alerts                          # evaluate watches, email/log alerts
# (also runs automatically at the end of every refresh-catalog)

# Inspect
python -m paliquor.cli stats                                 # product / UPC counts by category
```

## Tracking, value & alerts

- **Price/stock history** — every `refresh-catalog` records a `PriceSnapshot`
  per product when its price or stock changes. `GET /api/products/{code}/history`
  feeds the sparkline in the product drawer. Run refresh on a schedule (e.g.
  Task Scheduler / cron) to build history over time.
- **Value & discounts** — products carry `list_price`/`sale_price` (so we flag
  discounts and savings), `proof`, and `volume_ml`. Sort by `value`
  ($/750 mL) or `proof_desc`; filter `on_sale=true`.
- **Watch & alerts** — `POST /api/products/{code}/watch {email, target_price?}`.
  After each refresh, watches that flip to in-stock or drop in price trigger an
  email (via SMTP if configured in `.env`, otherwise logged).

Whiskey category codes: `152` Bourbon · `156` Rye · `157` American · `159` Irish
· `158` Japanese · `153` Scotch · `160` Flavored · `161` Canadian · `162` More
Imported.

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/products?q=&category=&sort=&chairmans=&on_sale=&limit=&offset=` | search/list (name or UPC; sort `name`/`price_asc`/`price_desc`/`value`/`proof_desc`) |
| `GET /api/products/{code}` | one product with UPCs + statewide availability |
| `GET /api/products/{code}/availability?store_code=` | statewide + best-effort per-store |
| `GET /api/products/{code}/history` | price/stock snapshots over time |
| `POST /api/products/{code}/watch` `{email, target_price?}` | watch for restock / price drop |
| `DELETE /api/products/{code}/watch?email=` · `GET /api/watches?email=` | manage watches |
| `GET /api/counties` | PA counties with store counts |
| `GET /api/counties/{county}/stores` | stores in a county |
| `GET /api/meta` | catalog stats + data-source disclosure |

## Configuration (`.env`)

| Var | Default | Meaning |
|-----|---------|---------|
| `CONTACT_EMAIL` | — | included in the User-Agent so the site can reach you |
| `PROJECT_URL` | — | included in the User-Agent |
| `MIN_REQUEST_INTERVAL` | `2.0` | seconds between catalog HTTP requests |
| `CATALOG_TTL_HOURS` | `168` | catalog cache lifetime |
| `INVENTORY_TTL_HOURS` | `6` | per-store check cache lifetime |
| `BROWSER_CONCURRENCY` | `1` | headless-browser parallelism (keep low) |
