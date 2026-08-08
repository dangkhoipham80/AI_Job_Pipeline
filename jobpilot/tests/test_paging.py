"""Pagination, and the two ways it goes wrong quietly.

The obvious half — "does `?limit=2&offset=2` return the third and fourth row" —
is barely worth a test. These pin the parts that fail *without an error*:

1. **A window with no total order.** `LIMIT/OFFSET` over an ordering that has
   ties is not deterministic. The database is free to order the ties one way
   for the page-1 query and another way for the page-2 query, so one row is
   served twice and another is never served at all. Nothing raises; you simply
   never see a job. Every paginated query here ends in a unique column, and
   `test_paging_a_tied_ordering_*` is what keeps it that way — the fixtures
   deliberately give every row the *same* sort key so the tie-break is the only
   thing doing any work.

2. **A total that doesn't match its filter.** `total` is what the UI divides to
   get a page count, so a total counted over the whole table while the rows are
   filtered produces pages 4 through 9 that are all empty.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobpilot.api.deps import get_db
from jobpilot.api.main import app
from jobpilot.api.schemas import MAX_PAGE_SIZE
from jobpilot.config import get_secrets
from jobpilot.store.models import Job, JobStatus

AUTH = {"X-API-Token": get_secrets().jobpilot_api_token}


@pytest.fixture
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Twelve jobs that all tie on every sort key the endpoint offers: no
    # `posted_at`, no `crawled_at`. If the ordering did not end in `Job.id`,
    # the rows would come back in whatever order the planner felt like.
    with session_factory() as s:
        s.add_all(
            Job(
                id=f"itviec:{i:02d}",
                source="itviec" if i % 2 else "topcv",
                title=f"Job {i:02d}",
                company="ACME",
                status=JobStatus.DISCOVERED,
            )
            for i in range(12)
        )
        s.commit()

    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _page(client, **params) -> dict:
    r = client.get("/jobs", params=params, headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_window_reports_the_total_behind_it(client):
    """`len(items)` cannot answer "is there more?" — a page of 5 out of 5 and a
    page of 5 out of 900 are the same array on the wire."""
    body = _page(client, limit=5)
    assert len(body["items"]) == 5
    assert body["total"] == 12
    assert body["limit"] == 5 and body["offset"] == 0


def test_walking_the_pages_yields_every_row_exactly_once(client):
    """The tie-break test. Every seeded job has a null `posted_at`, so the
    only thing separating them is `Job.id` — remove it from the ORDER BY and
    this is the test that starts flaking."""
    seen: list[str] = []
    for offset in range(0, 12, 5):
        seen.extend(j["id"] for j in _page(client, limit=5, offset=offset)["items"])

    assert len(seen) == 12, "a row was served twice or skipped"
    assert len(set(seen)) == 12
    assert seen == sorted(seen, reverse=True), "pages must stay in one global order"


def test_the_total_is_counted_with_the_same_filter_as_the_rows(client):
    """A total counted over the table instead of the query offers the user
    pages that come back empty."""
    body = _page(client, source="itviec", limit=2)
    assert body["total"] == 6, "six of the twelve are itviec"
    assert len(body["items"]) == 2
    assert all(j["source"] == "itviec" for j in body["items"])


def test_an_offset_past_the_end_is_an_empty_page_not_an_error(client):
    body = _page(client, limit=5, offset=99)
    assert body["items"] == []
    # The total still describes the result, so the UI can say "you're past the
    # end" and offer a way back rather than showing a bare empty list.
    assert body["total"] == 12


def test_the_page_size_is_capped(client):
    """`/applications` used to take an uncapped `limit`. An unbounded list
    endpoint is a denial of service against your own dashboard, so asking for
    too much is a 422 rather than a slow success."""
    assert client.get("/jobs", params={"limit": MAX_PAGE_SIZE + 1}, headers=AUTH).status_code == 422
    assert client.get("/jobs", params={"limit": 0}, headers=AUTH).status_code == 422
    assert client.get("/jobs", params={"offset": -1}, headers=AUTH).status_code == 422
    assert client.get("/jobs", params={"limit": MAX_PAGE_SIZE}, headers=AUTH).status_code == 200


def test_paginated_queries_must_declare_an_order(session_factory):
    """The helper refuses an unordered statement rather than producing a page
    that is only accidentally correct."""
    from sqlalchemy import select

    from jobpilot.api.paging import page_query

    with session_factory() as db:
        with pytest.raises(ValueError, match="ORDER BY"):
            page_query(db, select(Job), limit=5, offset=0)
