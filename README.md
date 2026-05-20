# PaLiquor — Pennsylvania Bourbon Finder

Browse Pennsylvania (Fine Wine & Good Spirits / PLCB) **bourbon & whiskey** by
county and store, with UPCs, prices, and on-demand store availability.

## Data sources & how we use them

All data comes from publicly accessible Pennsylvania PLCB resources:

- **Product catalog** (names, UPCs, prices): the publicly served product pages on
  `finewineandgoodspirits.com`, which embed [schema.org `Product`](https://schema.org/Product)
  JSON-LD — structured data published specifically for machine consumption.
- **Product discovery**: the site's published `sitemap.xml` and category pages.
- **Per-store inventory**: fetched **on demand** (when a user views a product) using a
  real headless browser that runs the site's own JavaScript, then **cached** for a
  while so we don't re-fetch repeatedly.

### Operating principles (please keep these)

This project is built to be a *polite, honest* client, not to evade anything:

- Identifies itself with a truthful `User-Agent` including a contact address.
- Honors `robots.txt` (notably: never touches `/searchresults`).
- Conservative, human-like request rates with caching and incremental updates.
- **Does not** forge anti-bot tokens, rotate proxies to dodge bans, or otherwise
  disguise automated traffic. If the site asks us to slow down or stop, we do.

> Before running this publicly, review the FWGS Terms of Use. This tool is for
> personal/informational use (price & availability lookup).

## Layout

```
src/paliquor/
  config.py        # settings: rate limits, user-agent, contact, TTLs
  http_client.py   # polite throttled HTTP client (catalog fetches)
  models.py        # SQLAlchemy models
  db.py            # engine/session helpers
  catalog.py       # parse product pages -> Product (UPC, price, ...)
  enumerate.py     # Playwright: discover bourbon/whiskey SKUs by category
  inventory.py     # Playwright: per-store availability, cached
  stores.py        # store directory (county -> stores)
  api.py           # FastAPI app
  cli.py           # command-line entrypoints
web/               # static frontend
data/              # sqlite db + http cache (gitignored)
```

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
playwright install chromium

# set your contact address so requests identify honestly
copy .env.example .env   # then edit CONTACT_EMAIL

python -m paliquor.cli init-db
python -m paliquor.cli refresh-catalog        # discover + parse bourbon/whiskey
python -m paliquor.cli import-stores          # store directory from OpenStreetMap
uvicorn paliquor.api:app --reload             # serve API + frontend
```

### Store directory

`import-stores` pulls from OpenStreetMap (free, but incomplete in some counties).
For complete, authoritative coverage of all ~568 stores, load the official PLCB
list — see [STORES.md](STORES.md):

```powershell
python -m paliquor.cli import-stores-csv path\to\official_stores.csv --replace
```
