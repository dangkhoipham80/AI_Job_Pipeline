"""Shared paging helpers for the list endpoints.

Two things every paginated query needs and one of them is easy to forget.

**The total.** ``Page.total`` is counted with the same filters as the window,
via a subquery over the filtered statement rather than a hand-rebuilt
``select(count()).where(...)``. Rebuilding the filters by hand is how a total
drifts away from the rows it is supposed to count: someone adds a `level`
filter to the window and not to the count, and the pager offers a page 4 that
comes back empty.

**A total order.** ``LIMIT/OFFSET`` over a non-deterministic order is a silent
correctness bug, not a cosmetic one: rows that tie on the sort key may come
back in a different order on the next query, so the same row appears on page 1
*and* page 2 while another is never shown at all. Postgres will happily do this
— the plan is free to change between two identical queries. So every ordering
here ends in a unique tie-break (the primary key), and :func:`page_query`
refuses a statement with no ORDER BY at all.
"""

from __future__ import annotations

from typing import TypeVar

from fastapi import Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from jobpilot.api.schemas import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

T = TypeVar("T")


def LimitParam(default: int = DEFAULT_PAGE_SIZE) -> int:  # noqa: N802 - reads as a type
    """The `limit` query parameter, capped. Used as a default value."""
    return Query(default, ge=1, le=MAX_PAGE_SIZE, description="rows per page")


def OffsetParam() -> int:  # noqa: N802 - reads as a type
    """The `offset` query parameter."""
    return Query(0, ge=0, description="rows to skip")


def total_for(db: Session, stmt: Select) -> int:
    """Count the rows a filtered statement would return, ignoring its window."""
    # order_by has to go: Postgres rejects ORDER BY over a column that isn't in
    # the subquery's select list, and ordering a COUNT is pointless anyway.
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def page_query(db: Session, stmt: Select, limit: int, offset: int) -> tuple[list, int]:
    """Return ``(rows, total)`` for one window of an ordered statement."""
    if not stmt._order_by_clauses:
        raise ValueError(
            "paginated queries need an ORDER BY ending in a unique column — "
            "without one, LIMIT/OFFSET can show the same row on two pages"
        )
    total = total_for(db, stmt)
    rows = list(db.scalars(stmt.limit(limit).offset(offset)))
    return rows, total


def page_list(items: list[T], total: int, limit: int, offset: int) -> dict:
    """Envelope for lists that are already in memory (the task queue)."""
    return {"items": items, "total": total, "limit": limit, "offset": offset}
