"""The shared listing-page walk in ``BaseScraper.search``.

One fetch used to be the whole crawl, so ``jobs_per_site`` above a site's page
size quietly came back short — VietnamWorks lazy-loads ~9-20 cards and the rest
are skeletons awaiting a scroll. Paging fixes that, but it introduces its own
failure: a board that *accepts* ``?page=2`` and ignores it answers 200 with page
1 again. These tests pin both halves — that we page, and that we notice when
paging does nothing.
"""

from __future__ import annotations

import logging

import pytest

from jobpilot.crawler.base import BaseScraper
from jobpilot.crawler.ratelimit import RateLimiter
from jobpilot.crawler.types import RawJob, SearchHit


class PagedScraper(BaseScraper):
    """A board with ``per_page`` jobs per page and ``total`` jobs in all."""

    source = "paged"

    def __init__(self, *, total: int = 25, per_page: int = 10, honours_page: bool = True, **kw):
        kw.setdefault("rate_limiter", RateLimiter(0, 0))
        super().__init__(**kw)
        self.total = total
        self.per_page = per_page
        self.honours_page = honours_page
        self.fetched: list[str] = []
        self.fetcher = self._fetch_page

    def _fetch_page(self, url: str) -> str:
        self.fetched.append(url)
        page = int(url.rsplit("=", 1)[1])
        if not self.honours_page:
            page = 1  # the whole point: the parameter is accepted and ignored
        start = (page - 1) * self.per_page
        ids = range(start, min(start + self.per_page, self.total))
        return ",".join(str(i) for i in ids)

    def search_url(self, query: str, page: int = 1) -> str:
        return f"https://board.test/jobs?q={query}&page={page}"

    def parse_search(self, text: str) -> list[SearchHit]:
        return [
            SearchHit(native_id=i, url=f"https://board.test/j/{i}") for i in text.split(",") if i
        ]

    def parse_detail(self, text: str, hit: SearchHit) -> RawJob:
        return RawJob(source=self.source, native_id=hit.native_id, url=hit.url, title=hit.native_id)


def test_paging_reaches_a_limit_no_single_page_could():
    """The bug this phase fixes: 25 wanted, 10 per page."""
    scraper = PagedScraper(total=100, per_page=10)
    hits = scraper.search("java", limit=25)
    assert len(hits) == 30  # three pages fetched; crawl() trims to 25
    assert len(scraper.fetched) == 3


def test_one_page_is_enough_when_it_already_has_the_limit():
    """A 50-card board must not be paged for the sake of it."""
    scraper = PagedScraper(total=100, per_page=50)
    scraper.search("java", limit=10)
    assert len(scraper.fetched) == 1


def test_max_pages_is_a_hard_ceiling():
    scraper = PagedScraper(total=1000, per_page=10, max_pages=2)
    assert len(scraper.search("java", limit=500)) == 20
    assert len(scraper.fetched) == 2


def test_running_off_the_end_stops_quietly():
    scraper = PagedScraper(total=15, per_page=10)
    assert len(scraper.search("java", limit=100)) == 15
    # page 3 is empty and ends the walk; nothing beyond it is requested.
    assert len(scraper.fetched) == 3


def test_a_site_that_ignores_the_page_parameter_is_caught_and_reported(caplog):
    """Without cross-page dedup this collects the same 10 jobs five times and
    reports a successful deep sweep — the TopCV ``?keyword=`` failure again."""
    scraper = PagedScraper(total=100, per_page=10, honours_page=False)
    with caplog.at_level(logging.WARNING):
        hits = scraper.search("java", limit=50)

    assert len(hits) == 10  # not 50, and not 10 duplicated five times
    assert len({h.native_id for h in hits}) == 10
    assert len(scraper.fetched) == 2  # page 2 proved the point; no page 3
    assert any("ignoring the page parameter" in r.getMessage() for r in caplog.records)


def test_a_source_with_no_page_two_is_not_asked_twice():
    """Returning page 1's URL (or "") is how a single-page source opts out."""

    class SinglePage(PagedScraper):
        def search_url(self, query: str, page: int = 1) -> str:
            return "https://board.test/jobs?q=x&page=1"

    scraper = SinglePage(total=100, per_page=10)
    scraper.search("java", limit=50)
    assert len(scraper.fetched) == 1


def test_page_one_failure_fails_the_site_but_a_later_page_does_not():
    """Page 1 dying means the site is down — the pipeline isolates it. Page 3
    dying must not throw away a good page 1."""

    class FlakyLater(PagedScraper):
        def _fetch_page(self, url: str) -> str:
            if url.endswith("page=2"):
                raise RuntimeError("cloudflare")
            return super()._fetch_page(url)

    scraper = FlakyLater(total=100, per_page=10)
    assert len(scraper.search("java", limit=50)) == 10

    class FlakyFirst(PagedScraper):
        def _fetch_page(self, url: str) -> str:
            raise RuntimeError("cloudflare")

    with pytest.raises(RuntimeError, match="cloudflare"):
        FlakyFirst().search("java", limit=10)


def test_pages_after_the_first_are_rate_limited():
    """Paging is still N requests at somebody's site (principle 5)."""
    waits: list[int] = []
    limiter = RateLimiter(0, 0)
    limiter.wait = lambda: waits.append(1)  # type: ignore[method-assign]

    scraper = PagedScraper(total=100, per_page=10, rate_limiter=limiter)
    scraper.search("java", limit=25)
    assert len(waits) == 2  # before page 2 and page 3, not before page 1


def test_needs_detail_false_skips_the_detail_fetch():
    class FeedLike(PagedScraper):
        needs_detail = False

    scraper = FeedLike(total=5, per_page=10)
    jobs = scraper.crawl("java", limit=5)
    assert len(jobs) == 5
    assert len(scraper.fetched) == 1  # the listing only — no per-job requests


def test_needs_detail_true_still_fetches_each_job():
    scraper = PagedScraper(total=3, per_page=10)
    scraper.crawl("java", limit=3)
    assert [u for u in scraper.fetched if "/j/" in u] == [
        "https://board.test/j/0",
        "https://board.test/j/1",
        "https://board.test/j/2",
    ]


def test_a_page_with_nothing_relevant_does_not_end_the_walk():
    """A general board serves whole pages with no Java on them, and page N+1 may
    be full of it. Stopping at the first barren page silently truncates the
    crawl — seen live on Arbeitnow, whose page 3 had 100 jobs and 0 matches."""

    class OnlyPageThreeMatches(PagedScraper):
        def matches_query(self, hit: SearchHit, query: str) -> bool:
            return int(hit.native_id) >= 20

    scraper = OnlyPageThreeMatches(total=100, per_page=10, max_pages=5)
    hits = scraper.search("java", limit=5)
    assert len(scraper.fetched) == 3  # pages 1 and 2 were barren, not final
    # Page 3's matches, whole; crawl() is what trims to the limit.
    assert [h.native_id for h in hits] == [str(i) for i in range(20, 30)]


def test_repeated_ids_still_stop_the_walk_even_when_nothing_is_relevant():
    """The ignored-page-parameter check must not depend on relevance, or a site
    that loops the same irrelevant page would be re-fetched to the ceiling."""

    class NothingMatches(PagedScraper):
        def matches_query(self, hit: SearchHit, query: str) -> bool:
            return False

    scraper = NothingMatches(total=100, per_page=10, honours_page=False, max_pages=5)
    assert scraper.search("java", limit=5) == []
    assert len(scraper.fetched) == 2  # page 2 repeated page 1 → stop


def test_matches_query_filters_before_the_limit_is_counted():
    """A feed source has no server-side search, so relevance decides which hits
    fill the budget — otherwise `limit` is spent on jobs the pipeline drops."""

    class OddOnly(PagedScraper):
        def matches_query(self, hit: SearchHit, query: str) -> bool:
            return int(hit.native_id) % 2 == 1

    scraper = OddOnly(total=100, per_page=10)
    hits = scraper.search("java", limit=10)
    assert all(int(h.native_id) % 2 == 1 for h in hits)
    assert len(hits) >= 10
