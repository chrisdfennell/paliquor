# Loading the official PLCB store list

The bundled store directory comes from OpenStreetMap (community data), which is
incomplete in some counties. For complete, authoritative coverage of all ~568
Fine Wine & Good Spirits stores, load the official PLCB list.

## 1. Get the list

The store directory is **not published as a clean public dataset**, and the
FWGS store locator is bot-protected, so it can't be scraped politely. Obtain the
list through an official channel:

- **PLCB customer service:** 1-800-332-7522 — ask for the current store list /
  cost-center directory (they provide it; it's public record).
- **Right-to-Know (open records) request** to the PLCB.
- Any official export/spreadsheet you already have.

## 2. Format it as CSV

Header row required (column order doesn't matter; case-insensitive). Only
`store_code` and `county` are strictly needed; the rest enrich the UI.

```csv
store_code,name,county,city,address,zip,latitude,longitude
0218,Fine Wine & Good Spirits #0218,Allegheny,Pittsburgh,2947 West Liberty Ave,15216,40.3905,-80.0250
9024,Fine Wine & Good Spirits #9024,Butler,Cranberry Township,20111 Route 19,16066,,
```

See [data/stores.template.csv](data/stores.template.csv). County names should
match PA county names without the word "County" (e.g. `Butler`, not
`Butler County`).

## 3. Load it

```powershell
# --replace clears the OSM/example stores first so the official list is clean
python -m paliquor.cli import-stores-csv path\to\stores.csv --replace
python -m paliquor.cli stats
```

That's it — every county fills in immediately, and the per-store check works
against the official store codes.
