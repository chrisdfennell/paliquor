"""Engine/session helpers."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

_engine = None
_Session: sessionmaker[Session] | None = None


def _ensure() -> sessionmaker[Session]:
    global _engine, _Session
    if _Session is None:
        _engine = create_engine(get_settings().database_url, future=True)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _Session


def init_db() -> None:
    _ensure()
    Base.metadata.create_all(_engine)


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
