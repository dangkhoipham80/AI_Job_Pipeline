"""SQLAlchemy ORM models for JobPilot (PLAN.md §3.2).

Portable across Postgres (deployment) and SQLite (tests): JSON columns use
JSONB on Postgres and JSON elsewhere; the ``jobpilot`` schema is applied via
``Base.metadata`` and rewritten away for SQLite (see ``store/db.py``).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jobpilot.store.db import SCHEMA, Base

# JSONB on Postgres (GIN-indexable), plain JSON on SQLite.
JSONType = JSONB().with_variant(JSON(), "sqlite")

# Schema-qualified FK targets. SQLite rewrites the schema away via the engine's
# schema_translate_map, so these stay correct in tests too.
_JOBS_ID = f"{SCHEMA}.jobs.id"


class JobStatus(str, enum.Enum):
    """Per-job lifecycle (PLAN.md §4 state machine)."""

    DISCOVERED = "DISCOVERED"
    SHORTLISTED = "SHORTLISTED"
    TAILORING = "TAILORING"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class Job(Base):
    __tablename__ = "jobs"

    # id = "<source>:<native_id>" — dedup key (PLAN.md §3.1).
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    url: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(String(256), default="")
    company: Mapped[str] = mapped_column(String(256), default="")
    location: Mapped[str | None] = mapped_column(String(256), nullable=True)
    salary: Mapped[str | None] = mapped_column(String(128), nullable=True)
    level: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), default=JobStatus.DISCOVERED, index=True
    )
    match_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    apply_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    apply_target: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full normalized Job payload (JD markdown, skills, raw_html_ref, …).
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    applications: Mapped[list[Application]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    edits: Mapped[list[Edit]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey(_JOBS_ID, ondelete="CASCADE"), index=True)
    cv_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_letter_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)  # email|portal|external
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)  # success|failed
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[Job] = relationship(back_populates="applications")


class Edit(Base):
    __tablename__ = "edits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey(_JOBS_ID, ondelete="CASCADE"), index=True)
    round: Mapped[int] = mapped_column(Integer, default=1)
    instruction: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job: Mapped[Job] = relationship(back_populates="edits")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # crawl|tailor|apply
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stats: Mapped[dict] = mapped_column(JSONType, default=dict)
    log_ref: Mapped[str | None] = mapped_column(Text, nullable=True)


class CvVersion(Base):
    __tablename__ = "cv_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(16), index=True)  # master|tailored
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey(_JOBS_ID, ondelete="CASCADE"), nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[dict] = mapped_column(
        JSONType, default=dict
    )  # structured JSON (editor source of truth)
    tex_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    theme: Mapped[dict] = mapped_column(JSONType, default=dict)
    author: Mapped[str] = mapped_column(String(16), default="user")  # user|agent
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
