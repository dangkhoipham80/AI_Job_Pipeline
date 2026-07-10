"""Job listing + detail endpoints (read-only in Phase 2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.api.deps import get_db, require_token
from jobpilot.api.schemas import JobOut
from jobpilot.store.models import Job, JobStatus

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_token)])


@router.get("", response_model=list[JobOut])
def list_jobs(
    db: Session = Depends(get_db),
    source: str | None = None,
    status: JobStatus | None = None,
    level: str | None = None,
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
    # Freshness first (newest postings on top), then most recently crawled.
    stmt = stmt.order_by(Job.posted_at.desc(), Job.crawled_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


@router.get("/{job_id:path}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job
