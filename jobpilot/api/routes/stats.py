"""Dashboard stats: funnel by status + counts by source/level/day + fresh flag."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobpilot.api.deps import get_db, require_token
from jobpilot.api.schemas import OutcomeStats, StatsOut
from jobpilot.apply.outcome import outcome_counts
from jobpilot.config import get_config
from jobpilot.store.models import Job, JobStatus
from jobpilot.timeutil import vn_now

router = APIRouter(tags=["stats"], dependencies=[Depends(require_token)])


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)) -> StatsOut:
    status_rows = db.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    source_rows = db.execute(select(Job.source, func.count()).group_by(Job.source)).all()
    level_rows = db.execute(select(Job.level, func.count()).group_by(Job.level)).all()
    day_rows = db.execute(
        select(func.date(Job.crawled_at), func.count()).group_by(func.date(Job.crawled_at))
    ).all()

    # Seed every status at 0 so the funnel always renders all stages.
    by_status = {s.value: 0 for s in JobStatus}
    for st, n in status_rows:
        key = st.value if isinstance(st, JobStatus) else str(st)
        by_status[key] = n

    by_source = {src: n for src, n in source_rows}
    by_level = {(lvl or "unknown"): n for lvl, n in level_rows}
    by_day = {str(day): n for day, n in day_rows if day is not None}

    cutoff = vn_now() - timedelta(hours=get_config().crawl.fresh_hours)
    fresh = db.scalar(select(func.count()).where(Job.posted_at >= cutoff)) or 0

    total = sum(by_source.values())
    return StatsOut(
        total=total,
        fresh=fresh,
        by_status=by_status,
        by_source=by_source,
        by_level=by_level,
        by_day=by_day,
        # Counted from the event log, not from the funnel: `by_status` stops at
        # SUBMITTED by design, and everything worth knowing about a job search
        # happens after that (Phase 18).
        outcomes=OutcomeStats(**outcome_counts(db)),
    )
