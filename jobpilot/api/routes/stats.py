"""Dashboard stats: funnel by status + counts by source."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobpilot.api.deps import get_db, require_token
from jobpilot.api.schemas import StatsOut
from jobpilot.store.models import Job, JobStatus

router = APIRouter(tags=["stats"], dependencies=[Depends(require_token)])


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)) -> StatsOut:
    status_rows = db.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    source_rows = db.execute(select(Job.source, func.count()).group_by(Job.source)).all()

    # Seed every status at 0 so the dashboard funnel always has all stages.
    by_status = {s.value: 0 for s in JobStatus}
    for st, n in status_rows:
        key = st.value if isinstance(st, JobStatus) else str(st)
        by_status[key] = n

    by_source = {src: n for src, n in source_rows}
    total = sum(by_source.values())
    return StatsOut(total=total, by_status=by_status, by_source=by_source)
