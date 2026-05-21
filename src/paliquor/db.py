"""Engine/session helpers."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

# Columns added to `products` after the first release. SQLite supports
# ADD COLUMN, so we patch existing databases without a migration framework.
_PRODUCT_ADDED_COLUMNS = {
    "list_price": "FLOAT",
    "sale_price": "FLOAT",
    "is_chairmans": "BOOLEAN DEFAULT 0",
    "proof": "FLOAT",
    "volume_ml": "FLOAT",
}

_engine = None
_Session: sessionmaker[Session] | None = None


def _ensure() -> sessionmaker[Session]:
    global _engine, _Session
    if _Session is None:
        _engine = create_engine(get_settings().database_url, future=True)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _Session


def _migrate(engine) -> None:
    """Add any newly-introduced product columns to an existing DB."""
    insp = inspect(engine)
    if "products" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("products")}
    with engine.begin() as conn:
        for col, ddl in _PRODUCT_ADDED_COLUMNS.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE products ADD COLUMN {col} {ddl}"))


def init_db() -> None:
    _ensure()
    Base.metadata.create_all(_engine)
    _migrate(_engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = _ensure()
    s = factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
