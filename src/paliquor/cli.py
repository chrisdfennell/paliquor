"""Command-line entrypoints.

    python -m paliquor.cli init-db
    python -m paliquor.cli refresh-catalog [--categories 152,156] [--limit N]
    python -m paliquor.cli stats
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy import func, select

from .config import DEFAULT_CATEGORIES, WHISKEY_CATEGORIES
from .db import init_db, session_scope
from .models import Product, Upc
from .scraper import refresh_catalog


def _parse_categories(arg: str | None) -> list[str]:
    if not arg:
        return DEFAULT_CATEGORIES
    return [c.strip() for c in arg.split(",") if c.strip()]


def cmd_init_db(_args) -> None:
    init_db()
    print("Database initialized.")


def cmd_refresh_catalog(args) -> None:
    init_db()
    cats = _parse_categories(args.categories)
    labels = ", ".join(f"{c}={WHISKEY_CATEGORIES.get(c, '?')}" for c in cats)
    print(f"Refreshing catalog for: {labels}"
          + (f" (limit {args.limit}/category)" if args.limit else ""))
    stats = refresh_catalog(cats, limit=args.limit)
    print(f"Done. discovered={stats['discovered']} "
          f"parsed={stats['parsed']} errors={stats['errors']}")


def cmd_import_stores(_args) -> None:
    init_db()
    from .store_import import import_stores_from_osm
    print("Importing FWGS stores from OpenStreetMap + deriving counties (FCC geo)...")
    n = import_stores_from_osm()
    print(f"Loaded {n} stores into the directory.")


def cmd_import_stores_csv(args) -> None:
    init_db()
    from pathlib import Path
    from .stores import clear_stores, load_stores_csv
    path = Path(args.path)
    if not path.exists():
        raise SystemExit(f"file not found: {path}")
    if args.replace:
        removed = clear_stores()
        print(f"Cleared {removed} existing stores.")
    n = load_stores_csv(path)
    print(f"Loaded {n} stores from {path.name}.")


def cmd_stats(_args) -> None:
    init_db()
    with session_scope() as s:
        n_products = s.scalar(select(func.count(Product.id)))
        n_upcs = s.scalar(select(func.count(Upc.id)))
        n_priced = s.scalar(select(func.count(Product.id)).where(Product.price.is_not(None)))
        print(f"Products: {n_products}  |  with price: {n_priced}  |  UPCs: {n_upcs}")
        by_cat = s.execute(
            select(Product.category_label, func.count(Product.id))
            .group_by(Product.category_label)
        ).all()
        for label, count in by_cat:
            print(f"  {label or '(uncategorized)'}: {count}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="paliquor")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=cmd_init_db)

    rc = sub.add_parser("refresh-catalog")
    rc.add_argument("--categories", help="comma-separated category codes (default: bourbon 152)")
    rc.add_argument("--limit", type=int, help="max products per category (for testing)")
    rc.set_defaults(func=cmd_refresh_catalog)

    sub.add_parser("import-stores").set_defaults(func=cmd_import_stores)

    ic = sub.add_parser("import-stores-csv", help="load an official PLCB store list (CSV)")
    ic.add_argument("path", help="path to the CSV file")
    ic.add_argument("--replace", action="store_true",
                    help="clear existing stores first (recommended for the official list)")
    ic.set_defaults(func=cmd_import_stores_csv)

    sub.add_parser("stats").set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
