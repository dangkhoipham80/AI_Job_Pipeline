"""Shared fixtures: an in-memory SQLite DB standing in for Postgres.

The ``jobpilot`` schema is rewritten to the default via the engine's
schema_translate_map (wired in ``store.db.make_engine``), so the real models
run unchanged without a live Postgres.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from jobpilot.store.db import Base, make_engine


@pytest.fixture(autouse=True)
def _seed_with_sample_cv(monkeypatch):
    """The app bootstraps an *empty* CV — it ships no content. Tests need a
    realistic one to assert against, so ``ensure_master`` is pointed at the
    fictional ``cv/sample.py`` document for the whole suite."""
    from jobpilot.cv.sample import sample_document

    monkeypatch.setattr("jobpilot.cv.store.empty_document", sample_document)


@pytest.fixture
def engine():
    eng = make_engine(
        "sqlite://",  # in-memory
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture
def session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
