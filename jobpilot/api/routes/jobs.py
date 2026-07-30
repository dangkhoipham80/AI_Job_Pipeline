"""Job listing, detail, and early-funnel actions (shortlist / skip)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from jobpilot.api.deps import get_db, require_token
from jobpilot.api.schemas import JobDetailOut, JobIn, JobOut, JobPatch
from jobpilot.api.ws import manager
from jobpilot.config import get_config
from jobpilot.store.models import Job, JobStatus
from jobpilot.timeutil import vn_now

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_token)])

_SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_UNSAFE.sub("-", text.lower()).strip("-")[:80] or "job"


def _native_id(url: str) -> str:
    """A stable id from a posting URL. LinkedIn ids are the useful case:
    /jobs/view/4012345678 -> linkedin-4012345678, so re-pasting updates."""
    if not url:
        return ""
    linkedin = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", url, re.I)
    if linkedin:
        return f"linkedin-{linkedin.group(1)}"
    return _slug(url.split("?")[0].rstrip("/").rsplit("/", 1)[-1])


# Statuses from which a user may still shortlist/skip (before the tailor stage).
_EARLY = {JobStatus.DISCOVERED, JobStatus.SHORTLISTED, JobStatus.SKIPPED}


@router.get("", response_model=list[JobOut])
def list_jobs(
    db: Session = Depends(get_db),
    source: str | None = None,
    status: JobStatus | None = None,
    level: str | None = None,
    q: str | None = Query(None, description="search title/company"),
    fresh: bool = False,
    run_id: int | None = Query(None, description="only jobs discovered by this crawl"),
    crawled_after: datetime | None = Query(None, description="crawled at or after this time"),
    order: str = Query("posted", pattern="^(posted|crawled)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[Job]:
    stmt = select(Job)
    if source:
        stmt = stmt.where(Job.source == source)
    if status:
        stmt = stmt.where(Job.status == status)
    if level:
        stmt = stmt.where(Job.level == level)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Job.title.ilike(like), Job.company.ilike(like)))
    if fresh:
        cutoff = vn_now() - timedelta(hours=get_config().crawl.fresh_hours)
        stmt = stmt.where(Job.posted_at >= cutoff)
    if run_id is not None:
        stmt = stmt.where(Job.run_id == run_id)
    if crawled_after is not None:
        stmt = stmt.where(Job.crawled_at >= crawled_after)

    # Default: freshest posting first. "crawled" answers a different question —
    # what did the agent turn up most recently — so it is a separate ordering
    # rather than a tweak of the same one.
    key = Job.crawled_at if order == "crawled" else Job.posted_at
    stmt = stmt.order_by(key.desc(), Job.crawled_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


@router.post("", response_model=JobDetailOut, status_code=201)
async def create_job(body: JobIn, db: Session = Depends(get_db)) -> JobDetailOut:
    """Add a job by hand (source ``manual``).

    The escape hatch for postings no crawler can reach — LinkedIn above all,
    whose robots.txt disallows automated access to job pages. Paste the JD and
    the rest of the pipeline treats it like any other job.
    """
    if not body.title.strip() or not body.company.strip():
        raise HTTPException(status_code=422, detail="title and company are required")

    now = vn_now()
    # Stable id from the URL when there is one, so pasting the same posting
    # twice updates it instead of creating a duplicate.
    native = _native_id(body.url) or _slug(f"{body.company}-{body.title}")
    job_id = f"manual:{native}"

    job = db.get(Job, job_id)
    if job is None:
        job = Job(id=job_id, source="manual", crawled_at=now)
        db.add(job)

    job.url = body.url
    job.title = body.title.strip()
    job.company = body.company.strip()
    job.location = body.location
    job.salary = body.salary
    job.level = body.level
    job.apply_channel = body.apply_channel
    job.apply_target = body.apply_target or body.url or None
    job.posted_at = job.posted_at or now
    job.payload = {
        **(job.payload or {}),
        "skills": body.skills,
        "description_md": body.description_md,
        "is_fresh": True,
    }
    db.commit()
    db.refresh(job)
    await manager.broadcast({"type": "job_updated", "id": job.id, "status": job.status.value})
    return JobDetailOut.from_job(job)


@router.patch("/{job_id:path}", response_model=JobDetailOut)
async def patch_job(job_id: str, body: JobPatch, db: Session = Depends(get_db)) -> JobDetailOut:
    """Edit a job — mainly to paste in a description the source didn't carry.

    LinkedIn alert emails announce a job but not its text, so this is how a
    job goes from "found" to "tailorable".
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=422, detail="nothing to change")

    payload = dict(job.payload or {})
    for field in ("description_md", "skills"):
        if field in patch:
            payload[field] = patch.pop(field)
    # A pasted description means the job no longer needs one.
    if "description_md" in (body.model_dump(exclude_none=True)):
        payload.pop("needs_jd", None)
    job.payload = payload

    for field, value in patch.items():
        setattr(job, field, value)
    db.commit()
    db.refresh(job)
    await manager.broadcast({"type": "job_updated", "id": job.id, "status": job.status.value})
    return JobDetailOut.from_job(job)


@router.get("/{job_id:path}", response_model=JobDetailOut)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobDetailOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobDetailOut.from_job(job)


async def _transition(job_id: str, target: JobStatus, db: Session) -> JobDetailOut:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status not in _EARLY:
        raise HTTPException(
            status_code=409,
            detail=f"cannot {target.value.lower()} a job in status {job.status.value}",
        )
    job.status = target
    db.commit()
    db.refresh(job)
    await manager.broadcast({"type": "job_updated", "id": job.id, "status": job.status.value})
    return JobDetailOut.from_job(job)


@router.post("/{job_id:path}/shortlist", response_model=JobDetailOut)
async def shortlist_job(job_id: str, db: Session = Depends(get_db)) -> JobDetailOut:
    return await _transition(job_id, JobStatus.SHORTLISTED, db)


@router.post("/{job_id:path}/skip", response_model=JobDetailOut)
async def skip_job(job_id: str, db: Session = Depends(get_db)) -> JobDetailOut:
    return await _transition(job_id, JobStatus.SKIPPED, db)
