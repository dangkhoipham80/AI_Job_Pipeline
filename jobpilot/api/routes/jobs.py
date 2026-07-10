"""Job listing, detail, and early-funnel actions (shortlist / skip)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from jobpilot.api.deps import get_db, require_token
from jobpilot.api.schemas import JobDetailOut, JobOut
from jobpilot.api.ws import manager
from jobpilot.config import get_config
from jobpilot.store.models import Job, JobStatus
from jobpilot.timeutil import vn_now

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_token)])

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
    # Freshness first (newest postings on top), then most recently crawled.
    stmt = stmt.order_by(Job.posted_at.desc(), Job.crawled_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


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
