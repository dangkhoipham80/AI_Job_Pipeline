"""Pydantic response schemas for the API (serialize ORM rows)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jobpilot.cv.schema import CvDocument
from jobpilot.store.models import Job, JobStatus


class JobOut(BaseModel):
    """List-row projection (no heavy JD payload)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    url: str
    title: str
    company: str
    location: str | None
    salary: str | None
    level: str | None
    posted_at: datetime | None
    status: JobStatus
    match_score: float
    apply_channel: str | None
    apply_target: str | None
    crawled_at: datetime | None
    # Which crawl discovered this job (null for hand-added ones).
    run_id: int | None = None


class JobDetailOut(JobOut):
    """Detail view: adds JD payload fields pulled from ``Job.payload``."""

    skills: list[str] = []
    description_md: str = ""
    is_fresh: bool = False
    # True when the source announced the job but couldn't carry its text —
    # LinkedIn alerts, mainly. Paste one in before tailoring.
    needs_jd: bool = False

    @classmethod
    def from_job(cls, job: Job) -> "JobDetailOut":
        payload: dict[str, Any] = job.payload or {}
        return cls(
            **JobOut.model_validate(job).model_dump(),
            skills=payload.get("skills", []) or [],
            description_md=payload.get("description_md", "") or "",
            is_fresh=bool(payload.get("is_fresh", False)),
            needs_jd=bool(payload.get("needs_jd", False)),
        )


class StatsOut(BaseModel):
    total: int
    fresh: int
    by_status: dict[str, int]
    by_source: dict[str, int]
    by_level: dict[str, int]
    by_day: dict[str, int]  # crawled_at date (YYYY-MM-DD) -> count


# --------------------------------------------------------------------------- #
# CV Studio (Phase 4.5)
# --------------------------------------------------------------------------- #
class CvDocumentOut(BaseModel):
    """The structured CV plus which version it is."""

    scope: str
    version: int
    document: CvDocument


class CvVersionOut(BaseModel):
    """Version-history row (content omitted — fetch the detail endpoint for it)."""

    model_config = ConfigDict(from_attributes=True)

    version: int
    author: str
    created_at: datetime | None


class CvVersionDetailOut(CvVersionOut):
    document: CvDocument
    tex: str


class CvCompileOut(BaseModel):
    scope: str
    version: int
    pages: int
    pdf_url: str


# --------------------------------------------------------------------------- #
# Tailor + CV Review (Phase 5)
# --------------------------------------------------------------------------- #
class TailorIn(BaseModel):
    instruction: str


class TailorOut(BaseModel):
    """Result of one tailor round. ``plan``/``diff`` are passed through as-is so
    the UI and the stored ``cv_versions.meta`` always agree."""

    job_id: str
    version: int
    round: int
    attempts: int
    pages: int | None
    match_score: float
    plan: dict
    diff: dict


class JobIn(BaseModel):
    """Add a job by hand — the path for anything the crawlers can't reach.

    Mostly LinkedIn: its robots.txt forbids automated access to job pages, so you
    find the posting yourself and paste it here. Everything downstream (tailor,
    review, apply) then works exactly as it does for a crawled job.
    """

    url: str = ""
    title: str
    company: str
    location: str | None = None
    salary: str | None = None
    level: str | None = None
    description_md: str = ""
    skills: list[str] = []
    # Defaults to external — you submit it yourself, which is the honest default
    # for a job we couldn't crawl.
    apply_channel: str = "external"
    apply_target: str | None = None


class JobPatch(BaseModel):
    """Fill in or correct a job. Only the fields present are touched, so pasting
    a description can't wipe the title."""

    title: str | None = None
    company: str | None = None
    location: str | None = None
    salary: str | None = None
    level: str | None = None
    url: str | None = None
    description_md: str | None = None
    skills: list[str] | None = None
    apply_channel: str | None = None
    apply_target: str | None = None


class ApplyIn(BaseModel):
    # None = generate a cover letter when a Claude key is configured.
    cover_letter: bool | None = None


class FailureIn(BaseModel):
    reason: str = ""


class ApplyOut(BaseModel):
    """``result`` is the important field: success | dry_run | awaiting_user | failed.
    A 200 here does not mean anything was sent."""

    job_id: str
    channel: str
    result: str
    detail: str
    application_id: int | None = None
    email: dict | None = None
    handoff: dict | None = None


class ApplicationOut(BaseModel):
    """One card on the Applications board."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    job_title: str
    company: str
    job_status: JobStatus
    channel: str | None
    result: str | None
    error_msg: str | None
    submitted_at: datetime | None
    created_at: datetime | None
    cv_pdf_path: str | None
    apply_target: str | None
    meta: dict = {}

    @classmethod
    def from_row(cls, app: Any, job: Job) -> "ApplicationOut":
        return cls(
            id=app.id,
            job_id=app.job_id,
            job_title=job.title,
            company=job.company,
            job_status=job.status,
            channel=app.channel,
            result=app.result,
            error_msg=app.error_msg,
            submitted_at=app.submitted_at,
            created_at=app.created_at,
            cv_pdf_path=app.cv_pdf_path,
            apply_target=job.apply_target,
            meta=app.meta or {},
        )


# --------------------------------------------------------------------------- #
# Orchestration (Phase 8)
# --------------------------------------------------------------------------- #
class TaskOut(BaseModel):
    """A queued/running/finished background task."""

    id: str
    kind: str
    label: str
    job_id: str | None = None
    status: str  # queued | running | done | failed
    progress: str = ""
    result: dict = {}
    error: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class RunOut(BaseModel):
    """One persisted run from the ``runs`` table."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    started_at: datetime | None
    finished_at: datetime | None
    stats: dict = {}
    # How many jobs this crawl actually put in the database, counted from the
    # jobs themselves rather than trusted from the run's own stats blob.
    job_count: int = 0


class SettingsIn(BaseModel):
    """Partial settings patch. Only the sections present are touched, so the
    Settings page can save one card without clobbering the rest."""

    app: dict | None = None
    crawl: dict | None = None
    apply: dict | None = None
    cv: dict | None = None
    sources: list[dict] | None = None


class ReviewOut(BaseModel):
    """What the CV Review page reads. All tailor fields are null before the first
    round, so the page can render an untailored job without special-casing."""

    job_id: str
    version: int
    author: str | None
    created_at: datetime | None
    match_score: float | None = None
    pages: int | None = None
    round: int = 0
    instruction: str | None = None
    plan: dict | None = None
    diff: dict | None = None
    gaps: list[dict] = []


class CrawlRequest(BaseModel):
    """One crawl's scope. Every field is optional and applies to this run only —
    nothing here is written back to config, so narrowing a single crawl can't
    quietly become the new default."""

    query: str | None = None
    # Subset of the sources enabled in Settings. None = all of them.
    sources: list[str] | None = None
    limit: int | None = Field(None, ge=1, le=200, description="jobs per site")
    no_robots: bool = False
