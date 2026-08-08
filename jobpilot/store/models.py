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
    suggestions: Mapped[list[InboxSuggestion]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="InboxSuggestion.id",
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


class InboxSuggestion(Base):
    """A message from your mailbox, and what it looks like it means (Phase 19).

    A suggestion, never an outcome. It carries the sentence it was judged on so
    you can overrule the label by reading one line, and it only becomes an
    ``application_events`` row when you accept it.

    ``mail_key`` is the message's own ``Message-ID`` rather than its IMAP uid:
    uids are per-folder and are re-issued when the server's UIDVALIDITY changes,
    so keying on one would re-classify the whole mailbox — and bill for it —
    the first time that happened.
    """

    __tablename__ = "inbox_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey(_APPLICATIONS_ID, ondelete="CASCADE"), index=True
    )
    mail_key: Mapped[str] = mapped_column(String(512), index=True)
    mail_from: Mapped[str] = mapped_column(String(320), default="")
    # Text, not VARCHAR: a subject is written by a stranger and Postgres would
    # be the one to find out it was too long, mid-flush, taking the batch with it.
    mail_subject: Mapped[str] = mapped_column(Text, default="")
    mail_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # How the message was tied to this application: thread|address|domain|company.
    match_confidence: Mapped[str] = mapped_column(String(16), default="")
    match_reason: Mapped[str] = mapped_column(Text, default="")
    # The proposed outcome, or auto_ack / unrelated when it isn't one.
    verdict: Mapped[str] = mapped_column(String(32), index=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    round_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # pending | accepted | dismissed | ignored (not an outcome, so never offered)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    application: Mapped[Application] = relationship(back_populates="suggestions")


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


class LlmCall(Base):
    """One round-trip to a model, priced and timed (Phase 20b).

    Written for every round, including the ones the guardrail rejected. A
    backend that is cheap per call and needs two rounds half the time is not
    cheap, and a table that only recorded the accepted round would hide exactly
    that — it would make the worst provider look like the best one at ranking
    time.

    ``cost_usd`` is nullable and stays NULL when the model is missing from
    ``llm/pricing.py``. That is a different fact from "it was free", and the
    difference matters most in the column people sort by.

    Not a column on ``applications``: this is data to GROUP BY, and half of it
    (tailor rounds for a job that was never applied to) belongs to no
    application at all.
    """

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # tailor | letter | classify — a plain String for the same reason
    # ApplicationEvent.event_type is one: the set grows, ALTER TYPE hurts.
    task: Mapped[str] = mapped_column(String(16), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(64), index=True)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    #: Which round this was: 1 is the first ask, 2 the corrective one. The
    #: share of work that lands on round 1 is the guardrail pass rate.
    round: Mapped[int] = mapped_column(Integer, default=1)
    #: Whether the task as a whole ended up with an answer the guardrails
    #: accepted. Repeated on every round of the same task on purpose — it makes
    #: "what fraction of attempts succeed" a query with no join in it.
    #: Defaults False for the same reason ``CallLog.accepted`` does: a row whose
    #: outcome nobody set is not a success nobody got.
    ok: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    #: Set when the call failed outright (no answer at all, as opposed to an
    #: answer the guard rejected). Keeps a dead API key from reading as a
    #: quality problem.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    job_id: Mapped[str | None] = mapped_column(
        ForeignKey(_JOBS_ID, ondelete="SET NULL"), nullable=True, index=True
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey(_APPLICATIONS_ID, ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
