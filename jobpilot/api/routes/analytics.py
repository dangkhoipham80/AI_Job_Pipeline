"""Market analytics (Phase 21).

One endpoint, one payload: the page draws eight charts and eight round-trips
would make it slower and its loading states harder to be honest about.

Read-only and derived entirely from `jobs.payload`, so it costs a query and no
model calls.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from jobpilot.analytics.market import market_report
from jobpilot.api.deps import get_db, require_token

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(require_token)])


@router.get("/market")
def market(db: Session = Depends(get_db)) -> dict:
    """Facets of the crawled corpus, each carrying its own coverage.

    Deliberately untyped by a response_model: every value is a `Facet` of the
    same shape, and spelling that out as eight identical Pydantic fields would
    add ceremony without adding a guarantee the dataclass does not already give.
    """
    return market_report(db)
