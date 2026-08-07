"""Arbeitnow parser contract, pinned against a trimmed real API response.

Field names and shapes are copied from ``/api/job-board-api``: the id really is
a slug, ``created_at`` really is unix seconds, ``location`` really says
"Homeoffice", and the feed really does mix trades — this is a general job board,
not a programming one.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from jobpilot.crawler.arbeitnow import API_URL, ArbeitnowScraper
from jobpilot.crawler.feed import parse_json_feed
from jobpilot.crawler.normalize import VN_TZ, parse_posted_at
from jobpilot.crawler.types import SearchHit

import json

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=VN_TZ)

PAGE_1 = json.dumps(
    {
        "data": [
            {
                "slug": "java-backend-developer-berlin-8058",
                "company_name": "teccle group GmbH",
                "title": "Java Backend Developer (m/w/d)",
                "description": "<p>Spring Boot, PostgreSQL.</p><ul><li>3 Jahre</li></ul>",
                "remote": True,
                "url": "https://www.arbeitnow.com/jobs/companies/teccle/java-backend-developer",
                "tags": ["Engineering", "Remote"],
                "job_types": ["fulltime permanent"],
                "location": "Homeoffice",
                "created_at": 1785627015,
            },
            {
                "slug": "chief-executive-munich-9001",
                "company_name": "Acme AG",
                "title": "Chief Executive Officer",
                "description": "<p>Lead the company.</p>",
                "remote": False,
                "url": "https://www.arbeitnow.com/jobs/companies/acme/chief-executive",
                "tags": ["Directors", "Chief Executives"],
                "job_types": [],
                "location": "München",
                "created_at": 1785627000,
            },
            {
                # No slug → no stable id. Dropped rather than keyed off a URL
                # that changes between crawls and would defeat dedup.
                "slug": "",
                "company_name": "Ghost GmbH",
                "title": "Ghost role",
                "url": "https://www.arbeitnow.com/jobs/companies/ghost/role",
            },
        ],
        "meta": {"current_page": 1, "per_page": 175},
    }
)

PAGE_2 = json.dumps(
    {
        "data": [
            {
                "slug": "senior-java-engineer-hamburg-7777",
                "company_name": "Nord GmbH",
                "title": "Senior Java Engineer",
                "description": "<p>Java 21.</p>",
                "remote": True,
                "url": "https://www.arbeitnow.com/jobs/companies/nord/senior-java-engineer",
                "tags": ["Engineering"],
                "job_types": [],
                "location": "",
                "created_at": 1785620000,
            }
        ],
        "meta": {"current_page": 2, "per_page": 175},
    }
)

EMPTY = json.dumps({"data": [], "meta": {"current_page": 400}})


def _paged_fetcher(fetched: list[str]):
    pages = {1: PAGE_1, 2: PAGE_2}

    def fetch(url: str) -> str:
        fetched.append(url)
        return pages.get(int(url.rsplit("=", 1)[1]), EMPTY)

    return fetch


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def test_parse_search_reads_the_records():
    hits = ArbeitnowScraper(fetcher=lambda u: PAGE_1).parse_search(PAGE_1)
    assert [h.native_id for h in hits] == [
        "java-backend-developer-berlin-8058",
        "chief-executive-munich-9001",
    ]
    first = hits[0]
    assert first.title == "Java Backend Developer (m/w/d)"
    assert first.company == "teccle group GmbH"
    assert first.location == "Homeoffice"


def test_location_falls_back_to_remote_only_when_nothing_is_published():
    """ "Homeoffice" is a work arrangement, not a city — but it is what the board
    published, so it is kept rather than replaced by a guess."""
    hits = ArbeitnowScraper(fetcher=lambda u: PAGE_2).parse_search(PAGE_2)
    assert hits[0].location == "Remote"  # blank location + remote: true


def test_unix_timestamps_become_real_dates():
    """created_at is unix seconds; ISO parsing rejects them, so without explicit
    handling every Arbeitnow job lands with posted_at=None and can never be
    flagged fresh."""
    hits = ArbeitnowScraper(fetcher=lambda u: PAGE_1).parse_search(PAGE_1)
    posted = parse_posted_at(hits[0].posted_raw, NOW)
    assert posted is not None
    assert posted.year == 2026


def test_a_bare_year_is_not_read_as_a_timestamp():
    """An unbounded int() would date the job to January 1970 — a confident wrong
    answer, which is worse than "unknown"."""
    assert parse_posted_at("2026", NOW) is None


# --------------------------------------------------------------------------- #
# relevance — this board carries every trade
# --------------------------------------------------------------------------- #
def test_query_matching_uses_title_and_tags_not_the_description():
    scraper = ArbeitnowScraper(fetcher=lambda u: PAGE_1)
    java, ceo = scraper.parse_search(PAGE_1)
    assert scraper.matches_query(java, "Java Spring Boot") is True
    assert scraper.matches_query(ceo, "Java Spring Boot") is False
    # Matched on Arbeitnow's own tag, not on the title.
    assert scraper.matches_query(java, "Engineering") is True
    # The CEO posting's description says nothing about Java, and neither does a
    # match: relevance never reads the JD.
    assert scraper.matches_query(ceo, "Lead") is False


def test_irrelevant_jobs_do_not_consume_the_limit():
    fetched: list[str] = []
    scraper = ArbeitnowScraper(fetcher=_paged_fetcher(fetched), max_pages=3)
    jobs = scraper.crawl("Java", limit=2)
    # The CEO row never becomes a job; page 2 is walked to fill the budget.
    assert [j.native_id for j in jobs] == [
        "java-backend-developer-berlin-8058",
        "senior-java-engineer-hamburg-7777",
    ]
    assert fetched == [f"{API_URL}?page=1", f"{API_URL}?page=2"]


# --------------------------------------------------------------------------- #
# the crawl contract
# --------------------------------------------------------------------------- #
def test_paging_stops_on_the_empty_page_the_api_really_returns():
    """Past the end Arbeitnow answers 200 with an empty `data` list, not a 404."""
    fetched: list[str] = []
    scraper = ArbeitnowScraper(fetcher=_paged_fetcher(fetched), max_pages=5)
    scraper.search("Java", limit=100)
    assert fetched[-1] == f"{API_URL}?page=3"  # page 3 is empty and ends the walk
    assert len(fetched) == 3


def test_no_detail_request_and_never_auto_applies():
    fetched: list[str] = []
    scraper = ArbeitnowScraper(fetcher=_paged_fetcher(fetched), max_pages=1)
    job = scraper.crawl("Java", limit=1)[0]

    assert fetched == [f"{API_URL}?page=1"]  # the listing only
    assert "Spring Boot" in job.description_html
    assert job.skills == ["Engineering", "Remote"]
    assert job.salary is None  # not published → None, not ""
    assert job.apply_channel == "external"  # robots disallows the apply route
    assert job.apply_target == job.url
    assert job.extra["source_name"] == "Arbeitnow"  # their terms ask for a link back


def test_html_error_page_fails_loudly_rather_than_as_zero_jobs():
    with pytest.raises(ValueError) as exc:
        parse_json_feed("<html><body>502 Bad Gateway</body></html>")
    assert "expected JSON" in str(exc.value)


def test_match_haystack_survives_a_missing_tags_key():
    scraper = ArbeitnowScraper()
    assert scraper.matches_query(SearchHit(native_id="1", url="u", title="Java Dev"), "java")


def test_freshness_window_still_works_off_an_epoch():
    """The point of a feed source is freshness, so the epoch has to land close
    enough to `now` for the <48h flag to fire."""
    recent = str(int((NOW - timedelta(hours=2)).timestamp()))
    posted = parse_posted_at(recent, NOW)
    assert posted is not None
    assert NOW - posted < timedelta(hours=3)
