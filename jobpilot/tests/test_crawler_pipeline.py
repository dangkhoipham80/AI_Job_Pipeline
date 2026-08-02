"""Phase 3: end-to-end crawl→normalize→filter→dedup→persist→Run on SQLite.

Uses the offline ``FixtureScraper`` so the whole pipeline runs without network,
Playwright, or Postgres.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from jobpilot.config import ApplyCfg, Config, CrawlCfg, CvCfg
from jobpilot.crawler.base import BaseScraper
from jobpilot.crawler.fixture import SEARCH_URL, FixtureScraper
from jobpilot.crawler.normalize import VN_TZ
from jobpilot.crawler.pipeline import run_crawl
from jobpilot.crawler.ratelimit import RateLimiter
from jobpilot.store.models import Job, JobStatus, Run

NOW = datetime(2026, 7, 10, 12, 0, tzinfo=VN_TZ)


def _cfg() -> Config:
    return Config(
        crawl=CrawlCfg(
            jobs_per_site=10,
            fresh_hours=48,
            stacks=["Java", "Spring Boot"],
            exclude_keywords=["Senior", "Lead"],
        ),
        apply=ApplyCfg(),
        cv=CvCfg(),
    )


def _detail(title, company, *, skills="Java", posted="2 days ago", jd="Build APIs") -> str:
    tags = "".join(f'<span class="skill">{s}</span>' for s in skills.split(","))
    return (
        f"<h1>{title}</h1><div class='company'>{company}</div>"
        f"<div class='location'>HCM</div><div class='posted'>{posted}</div>"
        f"{tags}<div class='jd'><p>{jd}</p></div>"
    )


def _pages() -> dict[str, str]:
    search = (
        '<a class="job" href="j/1" data-id="1">Backend Java</a>'
        '<a class="job" href="j/2" data-id="2">Senior Java</a>'  # excluded by title
        '<a class="job" href="j/3" data-id="3">Golang Dev</a>'  # no stack match → filtered
    )
    return {
        SEARCH_URL: search,
        "j/1": _detail("Backend Engineer Java", "ACME", skills="Java,Spring Boot"),
        "j/2": _detail("Senior Java Engineer", "BigCo", skills="Java"),
        "j/3": _detail("Golang Developer", "GoCorp", skills="Go"),
    }


def _fixture(pages, *, source="fixture") -> FixtureScraper:
    # Disable rate-limit sleeping so tests are instant.
    return FixtureScraper(pages, source=source, rate_limiter=RateLimiter(0, 0))


def test_pipeline_persists_filtered_normalized_jobs(session_factory):
    with session_factory() as db:
        report = run_crawl([_fixture(_pages())], _cfg(), db, now=NOW)

    assert report.totals.fetched == 3
    assert report.totals.inserted == 1  # only the Java backend survives filters
    assert report.totals.filtered == 2  # Senior (excluded) + Golang (no stack)

    with session_factory() as db:
        job = db.get(Job, "fixture:1")
        assert job is not None
        assert job.status is JobStatus.DISCOVERED
        assert job.company == "ACME"
        assert job.level is None
        assert job.match_score == 1.0  # both stacks present
        assert job.payload["is_fresh"] is True  # posted 2 days ago, fresh_hours=48 → 48h boundary
        assert db.get(Job, "fixture:2") is None
        assert db.get(Job, "fixture:3") is None


def test_run_row_recorded_with_stats(session_factory):
    with session_factory() as db:
        report = run_crawl([_fixture(_pages())], _cfg(), db, now=NOW)
        run = db.get(Run, report.run_id)
        assert run is not None
        assert run.kind == "crawl"
        assert run.finished_at is not None
        assert run.stats["totals"]["inserted"] == 1


def test_recrawl_updates_not_duplicates(session_factory):
    with session_factory() as db:
        run_crawl([_fixture(_pages())], _cfg(), db, now=NOW)
    with session_factory() as db:
        report = run_crawl([_fixture(_pages())], _cfg(), db, now=NOW)
        assert report.totals.inserted == 0
        assert report.totals.updated == 1
        assert db.query(Job).count() == 1  # no dupes


def test_cross_source_dedup_by_company_title(session_factory):
    # Same role on two "sources" → inserted once, second is a duplicate.
    pages_a = {
        SEARCH_URL: '<a class="job" href="a/1" data-id="1">x</a>',
        "a/1": _detail("Backend Engineer Java", "ACME", skills="Java,Spring Boot"),
    }
    pages_b = {
        SEARCH_URL: '<a class="job" href="b/1" data-id="9">x</a>',
        "b/1": _detail("Junior Backend Engineer Java", "ACME", skills="Java,Spring Boot"),
    }
    scrapers = [_fixture(pages_a, source="srcA"), _fixture(pages_b, source="srcB")]
    with session_factory() as db:
        report = run_crawl(scrapers, _cfg(), db, now=NOW)
        assert report.totals.inserted == 1
        assert report.totals.duplicates == 1


def test_site_failure_is_isolated(session_factory):
    class Boom(BaseScraper):
        source = "boom"

        def search_url(self, query, page=1):
            return "x"

        def parse_search(self, html):
            raise RuntimeError("cloudflare")

        def parse_detail(self, html, hit):  # pragma: no cover
            raise AssertionError

    boom = Boom(fetcher=lambda url: "<html></html>", rate_limiter=RateLimiter(0, 0))
    good = _fixture(_pages(), source="good")
    with session_factory() as db:
        report = run_crawl([boom, good], _cfg(), db, now=NOW)

    by_source = {s.source: s for s in report.sites}
    assert by_source["boom"].ok is False
    assert "cloudflare" in by_source["boom"].error
    assert by_source["good"].ok is True  # good site still ran
    assert report.totals.inserted == 1


def test_detail_fetch_error_skips_one_hit(session_factory):
    pages = _pages()
    del pages["j/1"]  # first detail page missing → KeyError → hit skipped
    with session_factory() as db:
        report = run_crawl([_fixture(pages)], _cfg(), db, now=NOW)
    assert report.totals.fetched == 2  # 3 hits, 1 detail fetch failed
    assert report.totals.inserted == 0  # remaining two are filtered out


@pytest.mark.parametrize("limit,expected", [(1, 1), (2, 2), (10, 3)])
def test_jobs_per_site_limit_respected(session_factory, limit, expected):
    cfg = _cfg()
    cfg.crawl.jobs_per_site = limit
    cfg.crawl.stacks = []  # disable stack filter so counts reflect the limit
    cfg.crawl.exclude_keywords = []
    with session_factory() as db:
        report = run_crawl([_fixture(_pages())], cfg, db, now=NOW)
    assert report.totals.fetched == expected


def test_zero_hits_is_warned_about_not_reported_as_a_quiet_success(caplog):
    """A parser whose selectors stopped matching returns [] and the crawl then
    "succeeds" with nothing to show — indistinguishable from a query that simply
    had no results. PLAN §10 wants that visible ("cảnh báo khi 0 job")."""
    scraper = _fixture({SEARCH_URL: "<html>redesigned, no job links</html>"})
    with caplog.at_level("WARNING"):
        assert scraper.crawl("java", limit=10) == []
    assert any("0 hits" in r.getMessage() for r in caplog.records)


def test_fewer_hits_than_requested_is_warned_about(caplog):
    """VietnamWorks lazy-loads: one fetch renders ~9-20 cards, so a limit above
    that is silently unsatisfiable from a single page."""
    with caplog.at_level("WARNING"):
        _fixture(_pages()).crawl("java", limit=10)
    assert any("wanted 10" in r.getMessage() for r in caplog.records)


def test_a_full_page_does_not_warn(caplog):
    with caplog.at_level("WARNING"):
        _fixture(_pages()).crawl("java", limit=3)
    assert not [r for r in caplog.records if "wanted" in (r.getMessage())]
