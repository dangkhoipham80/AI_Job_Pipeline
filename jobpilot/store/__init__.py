"""Persistence layer (PostgreSQL, SQLAlchemy 2.0 + Alembic). See PLAN.md §3.2."""

from jobpilot.store.db import Base, SCHEMA, get_engine, get_sessionmaker, make_engine, session_scope
from jobpilot.store.models import (
    Application,
    CvVersion,
    Edit,
    Job,
    JobStatus,
    Run,
)

__all__ = [
    "Base",
    "SCHEMA",
    "get_engine",
    "get_sessionmaker",
    "make_engine",
    "session_scope",
    "Job",
    "JobStatus",
    "Application",
    "Edit",
    "Run",
    "CvVersion",
]
