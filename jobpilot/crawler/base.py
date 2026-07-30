"""``BaseScraper`` — the per-site scraper contract + a shared crawl loop.

Subclasses implement three *pure* methods (``search_url``, ``parse_search``,
``parse_detail``) that never touch the network — they operate on HTML strings,
so they're unit-testable against snapshot fixtures (PLAN §5.1). ``crawl`` is the
template method that wires fetching, robots, rate-limiting and graceful
per-hit failure around them.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable

from jobpilot.crawler.ratelimit import RateLimiter
from jobpilot.crawler.robots import RobotsPolicy
from jobpilot.crawler.types import RawJob, SearchHit

log = logging.getLogger(__name__)

Fetcher = Callable[[str], str]


class RobotsDisallowed(RuntimeError):
    """A URL is disallowed by the site's robots.txt."""


class BaseScraper(ABC):
    source: str = "base"

    def __init__(
        self,
        *,
        fetcher: Fetcher | None = None,
        rate_limiter: RateLimiter | None = None,
        robots: RobotsPolicy | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.rate = rate_limiter or RateLimiter()
        self.robots = robots
        self._owned_fetcher = None  # lazily created default, closed by close()

    # -- pure, per-site (implement these) ---------------------------------- #
    @abstractmethod
    def search_url(self, query: str) -> str:
        """URL of the search/listing page for ``query``."""

    @abstractmethod
    def parse_search(self, html: str) -> list[SearchHit]:
        """Extract listing hits from a search page's HTML."""

    @abstractmethod
    def parse_detail(self, html: str, hit: SearchHit) -> RawJob:
        """Extract a full :class:`RawJob` from a detail page's HTML."""

    # -- fetching ----------------------------------------------------------- #
    def _resolve_fetcher(self) -> Fetcher:
        if self.fetcher is not None:
            return self.fetcher
        if self._owned_fetcher is None:
            from jobpilot.crawler.fetch import PlaywrightFetcher

            self._owned_fetcher = PlaywrightFetcher()
        return self._owned_fetcher

    def _fetch(self, url: str) -> str:
        if self.robots is not None and not self.robots.allowed(url):
            raise RobotsDisallowed(url)
        return self._resolve_fetcher()(url)

    def close(self) -> None:
        if self._owned_fetcher is not None:
            close = getattr(self._owned_fetcher, "close", None)
            if callable(close):
                close()
            self._owned_fetcher = None

    # -- crawl loop (template method) -------------------------------------- #
    def crawl(self, query: str = "", limit: int | None = None) -> list[RawJob]:
        """Search, then fetch+parse up to ``limit`` detail pages.

        A search-page failure aborts this site (propagates to the pipeline,
        which isolates it). A single detail-page failure is logged and skipped
        so one bad posting never sinks the batch.
        """
        search_html = self._fetch(self.search_url(query))
        hits = self.parse_search(search_html)
        # A parser whose selectors stopped matching returns [] and the crawl then
        # reports success with nothing to show — the exact failure PLAN §10 calls
        # out ("cảnh báo khi 0 job"). It is indistinguishable from a genuinely
        # empty result set, so say so loudly instead of logging it as normal.
        if not hits:
            log.warning(
                "[%s] search page parsed to 0 hits for query=%r — either the query "
                "has no results or the selectors no longer match the site",
                self.source,
                query,
            )
        elif limit is not None and len(hits) < limit:
            # e.g. VietnamWorks lazy-loads: one fetch renders ~9-20 cards.
            log.warning(
                "[%s] only %d hit(s) for query=%r, wanted %d — the listing page may "
                "load the rest on scroll",
                self.source,
                len(hits),
                query,
                limit,
            )
        if limit is not None:
            hits = hits[:limit]
        log.info("[%s] %d hit(s) for query=%r", self.source, len(hits), query)

        results: list[RawJob] = []
        for hit in hits:
            try:
                self.rate.wait()
                detail_html = self._fetch(hit.url)
                results.append(self.parse_detail(detail_html, hit))
            except Exception as exc:
                log.warning("[%s] skip %s: %s", self.source, hit.url, exc)
                continue
        return results
