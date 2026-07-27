"""Pydantic response schemas for the API (serialize ORM rows)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

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


class JobDetailOut(JobOut):
    """Detail view: adds JD payload fields pulled from ``Job.payload``."""

    skills: list[str] = []
    description_md: str = ""
    is_fresh: bool = False

    @classmethod
    def from_job(cls, job: Job) -> "JobDetailOut":
        payload: dict[str, Any] = job.payload or {}
        return cls(
            **JobOut.model_validate(job).model_dump(),
            skills=payload.get("skills", []) or [],
            description_md=payload.get("description_md", "") or "",
            is_fresh=bool(payload.get("is_fresh", False)),
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
