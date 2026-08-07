"""ATS adapters (Greenhouse / Lever), pinned against trimmed real responses.

Both payloads carry a trap that a "does it parse?" test sails straight past:
Greenhouse double-encodes the description, and Lever dates in milliseconds while
never naming the employer at all.
"""

from __future__ import annotations

import json
import logging

import pytest

from jobpilot.crawler.ats import GreenhouseScraper, LeverScraper
from jobpilot.crawler.normalize import parse_posted_at
from jobpilot.crawler.text import html_to_markdown
from jobpilot.crawler.types import SearchHit

GREENHOUSE = json.dumps(
    {
        "meta": {"total": 2},
        "jobs": [
            {
                "id": 8503792002,
                "absolute_url": "https://job-boards.greenhouse.io/gitlab/jobs/8503792002",
                "title": "Backend Engineer (Ruby)",
                "company_name": "GitLab",
                "location": {"name": "Remote, Canada"},
                "first_published": "2026-07-08T05:58:03-04:00",
                "updated_at": "2026-07-30T08:48:22-04:00",
                "requisition_id": "6263",
                "departments": [{"name": "Engineering"}],
                "offices": [{"name": "Americas"}],
                "content": "&lt;p&gt;Build &amp;amp; ship Ruby services.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;5 years&lt;/li&gt;&lt;/ul&gt;",
            },
            {
                # No absolute_url → no link to hand back. Dropped, not guessed.
                "id": 9,
                "absolute_url": "",
                "title": "Ghost role",
                "company_name": "GitLab",
            },
        ],
    }
)

LEVER = json.dumps(
    [
        {
            "id": "ac978161-6f46-4f6b-ad9e-a258e642751c",
            "text": "Backend Software Engineer",
            "hostedUrl": "https://jobs.lever.co/palantir/ac978161-6f46-4f6b-ad9e-a258e642751c",
            "applyUrl": "https://jobs.lever.co/palantir/ac978161/apply",
            "createdAt": 1783000000000,
            "workplaceType": "hybrid",
            "categories": {
                "commitment": "Full-time",
                "location": "London, United Kingdom",
                "team": "Engineering",
            },
            "description": "<div>A World-Changing Company</div>",
            "lists": [{"text": "What We Value", "content": "<li>Java, Spring Boot</li>"}],
            "additional": "<div>Life at Palantir</div>",
        }
    ]
)


# --------------------------------------------------------------------------- #
# Greenhouse
# --------------------------------------------------------------------------- #
def test_greenhouse_reads_the_board():
    hits = GreenhouseScraper(boards=["gitlab"]).parse_search(GREENHOUSE)
    assert [h.native_id for h in hits] == ["8503792002"]
    assert hits[0].title == "Backend Engineer (Ruby)"
    assert hits[0].company == "GitLab"
    assert hits[0].location == "Remote, Canada"


def test_greenhouse_description_is_unescaped():
    """The API double-encodes: `content` arrives as "&lt;p&gt;…". Stored raw, the
    reader gets literal tags where the job description should be, and the tailor
    gets markup as prose."""
    s = GreenhouseScraper(boards=["gitlab"])
    job = s.parse_detail("", s.parse_search(GREENHOUSE)[0])
    assert "<p>" in job.description_html
    assert "&lt;" not in job.description_html
    # Exactly one level of unescaping: `&amp;` is the correct encoding of a
    # literal "&" *inside* the recovered HTML, so it must survive here and
    # resolve when the JD is turned into the markdown the tailor reads.
    assert "&amp;" in job.description_html
    assert "Build & ship Ruby services." in html_to_markdown(job.description_html)
    assert "- 5 years" in html_to_markdown(job.description_html)


def test_greenhouse_prefers_first_published_over_updated_at():
    """`updated_at` moves every time a recruiter fixes a typo, which would make a
    three-month-old req look posted today — and freshness drives the 🔥 flag."""
    hit = GreenhouseScraper(boards=["gitlab"]).parse_search(GREENHOUSE)[0]
    posted = parse_posted_at(hit.posted_raw)
    assert posted is not None
    assert (posted.month, posted.day) == (7, 8)  # first_published, not updated_at


def test_greenhouse_tags_come_from_departments_and_offices():
    s = GreenhouseScraper(boards=["gitlab"])
    job = s.parse_detail("", s.parse_search(GREENHOUSE)[0])
    assert job.skills == ["Engineering", "Americas"]
    assert job.apply_channel == "external"
    assert job.extra["ats"] == "greenhouse"


def test_greenhouse_board_url_asks_for_the_description():
    """Without `content=true` this becomes one request per job instead of one
    per company, which is the whole point of the adapter."""
    assert "content=true" in GreenhouseScraper().board_url("gitlab")


# --------------------------------------------------------------------------- #
# Lever
# --------------------------------------------------------------------------- #
def test_lever_reads_an_array_not_an_object():
    hits = LeverScraper(boards=["palantir"]).parse_search(LEVER)
    assert len(hits) == 1
    assert hits[0].title == "Backend Software Engineer"


def test_lever_company_comes_from_the_url():
    """Lever's payload never names the employer — only the board does, and the
    board slug is in every posting's hostedUrl."""
    assert LeverScraper(boards=["palantir"]).parse_search(LEVER)[0].company == "Palantir"


def test_lever_millisecond_timestamps_become_real_dates():
    """createdAt is milliseconds; the epoch guard accepts 9-11 digits so a stray
    13-digit number is not mistaken for a date. Convert at the source instead of
    loosening the guard for everyone."""
    hit = LeverScraper(boards=["palantir"]).parse_search(LEVER)[0]
    posted = parse_posted_at(hit.posted_raw)
    assert posted is not None
    assert posted.year == 2026


def test_lever_description_keeps_the_requirements():
    """Lever splits a posting across description / lists / additional. Keeping
    only `description` hands the tailor a company blurb with none of the
    requirements the CV has to answer."""
    s = LeverScraper(boards=["palantir"])
    job = s.parse_detail("", s.parse_search(LEVER)[0])
    assert "A World-Changing Company" in job.description_html
    assert "Java, Spring Boot" in job.description_html  # from `lists`
    assert "What We Value" in job.description_html
    assert "Life at Palantir" in job.description_html  # from `additional`


def test_lever_rejects_the_404_object():
    """A wrong or expired board token answers with an object, not an array. That
    must fail loudly — parsed leniently it would read as "this company has no
    open roles", and the board would stay silently dead."""
    with pytest.raises(ValueError, match="array"):
        LeverScraper(boards=["nope"]).parse_search('{"code":404}')


# --------------------------------------------------------------------------- #
# the shared board-per-page contract
# --------------------------------------------------------------------------- #
def test_each_configured_company_is_one_page():
    s = GreenhouseScraper(boards=["gitlab", "elastic"])
    assert "gitlab" in s.search_url("java", 1)
    assert "elastic" in s.search_url("java", 2)
    assert s.search_url("java", 3) == ""  # out of companies → the walk stops


def test_company_count_overrides_the_page_ceiling():
    """`crawl.max_pages` exists to stop us walking an unbounded board forever. A
    hand-written list of companies is already bounded by whoever wrote it."""
    s = LeverScraper(boards=["a", "b", "c", "d", "e", "f", "g"], max_pages=2)
    assert s.max_pages == 7


def test_no_companies_configured_says_so_plainly(caplog):
    """The generic zero-hits warning reads as "the parser broke" — a misleading
    thing to tell someone whose only mistake is an empty list."""
    fetched = []
    s = GreenhouseScraper(boards=[], fetcher=lambda u: fetched.append(u) or "{}")
    with caplog.at_level(logging.INFO):
        assert s.crawl("java", limit=5) == []
    assert fetched == []  # nothing was requested
    assert any("no company boards configured" in r.getMessage() for r in caplog.records)


def test_one_request_per_company_no_detail_fetches():
    fetched: list[str] = []

    def fetch(url: str) -> str:
        fetched.append(url)
        return GREENHOUSE

    jobs = GreenhouseScraper(boards=["gitlab"], fetcher=fetch).crawl("backend", limit=5)
    assert len(fetched) == 1
    assert len(jobs) == 1


# --------------------------------------------------------------------------- #
# ranking
# --------------------------------------------------------------------------- #
def test_closest_match_comes_first():
    """Verified live: "backend engineer java" against a 184-job board matched 44
    postings, and `limit` kept "AI Engineer" plus four "Customer Success
    Engineer" roles — all on the word *engineer* alone. Filtering harder would
    drop good jobs; ordering costs nothing."""
    s = GreenhouseScraper(boards=["x"])
    hits = [
        SearchHit(native_id="1", url="u1", title="AI Engineer"),
        SearchHit(native_id="2", url="u2", title="Backend Engineer, Java Platform"),
        SearchHit(native_id="3", url="u3", title="Backend Engineer"),
    ]
    ranked = s.rank_hits(hits, "backend engineer java")
    assert [h.native_id for h in ranked] == ["2", "3", "1"]


def test_ranking_is_stable_and_a_no_op_without_a_query():
    s = GreenhouseScraper(boards=["x"])
    hits = [SearchHit(native_id=str(i), url="u", title="Engineer") for i in range(4)]
    assert [h.native_id for h in s.rank_hits(hits, "engineer")] == ["0", "1", "2", "3"]
    assert s.rank_hits(hits, "") == hits
