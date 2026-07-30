"""SQLAlchemy engine, session factory, and declarative base.

Sync SQLAlchemy 2.0 over psycopg3 — matches the ``postgresql+psycopg`` URL in
config. All ORM tables live in the ``jobpilot`` Postgres schema; under SQLite
(tests) that schema is transparently rewritten to the default via
``schema_translate_map`` so the same models run without a live Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from jobpilot.config import get_secrets

SCHEMA = "jobpilot"

# Stable, autogenerate-friendly constraint names (keeps Alembic diffs clean).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)


def make_engine(url: str | None = None, **kwargs) -> Engine:
    """Create an Engine. For SQLite, wire the schema-translate map so the
    ``jobpilot`` schema collapses to the default (SQLite has no schemas)."""
    url = url or get_secrets().database_url
    if url.startswith("sqlite"):
        kwargs.setdefault("execution_options", {}).setdefault(
            "schema_translate_map", {SCHEMA: None}
        )
    else:
        kwargs.setdefault("pool_pre_ping", True)
    return create_engine(url, future=True, **kwargs)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Process-wide lazy singleton engine (built from Secrets.database_url)."""
    global _engine, _SessionLocal
    if _engine is None:
        _engine = make_engine()
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context-managed session for scripts/CLI (commit on success, rollback on error)."""
    db = get_sessionmaker()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
