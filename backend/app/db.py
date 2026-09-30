"""Database setup: SQLAlchemy engine/session. SQLite for demo, Postgres in prod.

Just set DATABASE_URL=postgresql+psycopg://user:pass@host:5432/medcheck
(install psycopg[binary]) — models are engine-agnostic.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        # ensure dir for sqlite file
        path = url.split("///")[-1]
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
    return create_engine(url, **kwargs)


_engine = None
_session_factory: sessionmaker | None = None


def init_db() -> None:
    global _engine, _session_factory
    settings = get_settings()
    _engine = _make_engine(settings.database_url)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    # import models so they register on the metadata
    from . import models  # noqa: F401

    Base.metadata.create_all(_engine)


def get_engine():
    if _engine is None:
        init_db()
    return _engine


def get_session() -> Session:
    if _session_factory is None:
        init_db()
    return _session_factory()


def session_scope() -> Iterator[Session]:
    """Context manager: commit on success, rollback on error."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """FastAPI dependency."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()
