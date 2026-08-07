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
    Boolean,
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
_APPLICATIONS_ID = f"{SCHEMA}.applications.id"


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
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    # The crawl that first discovered this job. Not updated on re-crawl: a job
    # belongs to the run that found it, not to every run that has seen it.
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    applications: Mapped[list[Application]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    edits: Mapped[list[Edit]] = relationship(back_populates="job", cascade="all, delete-orphan")

    @property
    def quality(self) -> dict | None:
        """Advisory signals stashed in the payload at crawl time.

        A property rather than a column: it is derived from fields already
        stored, and FastAPI serializes ORM rows straight through
        ``from_attributes``, so this is the one place both the list and the
        detail response will pick it up without either route knowing.
        """
        return (self.payload or {}).get("quality")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey(_JOBS_ID, ondelete="CASCADE"), index=True)
    cv_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The letter as text (what the email body carried) and as a built PDF. Two
    # columns because they fail apart: NULL pdf with a non-NULL txt means the
    # LaTeX build didn't run or didn't work, and `meta["letter"]["pdf_error"]`
    # says which. Collapsing them would make "no PDF" indistinguishable from
    # "no letter".
    cover_letter_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_letter_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)  # email|portal|external
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # success | failed | dry_run | awaiting_user
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Channel-specific detail: the email summary, or the portal handoff package.
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Where you are in the follow-up cadence, and when the next step is due.
    # Both NULL when nothing actually went out — a dry run owes no follow-up,
    # and NULL says that more honestly than a date already in the past.
    next_followup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    followup_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The most recent outcome recorded for this application, denormalized off
    # ``application_events`` so the board can render 200 cards without 200
    # subqueries. NULL means nothing has been recorded yet — which is not the
    # same as nothing having happened, and the board says so.
    outcome_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)

    job: Mapped[Job] = relationship(back_populates="applications")
    events: Mapped[list[ApplicationEvent]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationEvent.id",
    )


class ApplicationEvent(Base):
    """One thing that happened after the application went out (Phase 18).

    Append-only, like ``cv_versions``: an outcome you recorded and then
    corrected is still evidence about how the search is going, and the analytics
    phase needs the *sequence* — an application rejected after two interviews is
    a different story from one rejected on day one, and ``outcome_stage`` alone
    tells both of them as "rejected".

    ``occurred_at`` and ``recorded_at`` are separate on purpose. Time-to-reply is
    measured from when the employer actually replied, not from when you got
    around to typing it in — and Phase 19 (inbox sync) will be typing it in days
    late by definition.
    """

    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey(_APPLICATIONS_ID, ondelete="CASCADE"), index=True
    )
    # replied | interview | offer | rejected | withdrawn | ghosted.
    # Deliberately a String, not a Postgres enum: the set will grow (Phase 19
    # brings employer-reply subtypes), and ALTER TYPE can't run inside a
    # transaction block, so every future value would cost an awkward migration.
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Soft delete for the mis-click. Retracting rewinds ``outcome_stage`` to the
    # previous live event rather than deleting the row, because "I recorded this
    # by mistake" is itself part of the history.
    is_retracted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Where the follow-up cadence stood just before this event silenced it.
    # Recording an outcome sets the application to `done`, so without these two
    # a fully retracted mistake would leave the cadence stopped forever with no
    # outcome to justify it — the reminder quietly lost, and no way to ask for
    # it back. Stored per event so retracting restores the exact position rather
    # than recomputing an approximation of it.
    prev_followup_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prev_followup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    application: Mapped[Application] = relationship(back_populates="events")


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
    # Tailor output for agent versions: match_score, requirements, gaps, changes,
    # diff (Phase 5). Empty for hand edits made in CV Studio.
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
