"""``BaseScraper`` — the per-site scraper contract + a shared crawl loop.

Subclasses implement three *pure* methods (``search_url``, ``parse_search``,
``parse_detail``) that never touch the network — they operate on text (HTML,
RSS or JSON), so they're unit-testable against snapshot fixtures (PLAN §5.1).
``crawl`` is the template method that wires fetching, robots, rate-limiting,
pagination and graceful per-hit failure around them.
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

#: How many listing pages one site may be asked for in a single crawl. A guard
#: against walking a board forever, not a target: the loop stops as soon as it
#: has ``limit`` hits, which for a 50-card page is page 1.
DEFAULT_MAX_PAGES = 5


class RobotsDisallowed(RuntimeError):
    """A URL is disallowed by the site's robots.txt."""


class BaseScraper(ABC):
    source: str = "base"

    #: False when the listing already carries the whole job, so there is no
    #: detail page worth fetching. Official feeds ship the full description
    #: inline; requesting each job page again would be N pointless requests.
    needs_detail: bool = True

    def __init__(
        self,
        *,
        fetcher: Fetcher | None = None,
        rate_limiter: RateLimiter | None = None,
        robots: RobotsPolicy | None = None,
        max_pages: int | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.rate = rate_limiter or RateLimiter()
        self.robots = robots
        self.max_pages = max_pages if max_pages is not None else DEFAULT_MAX_PAGES
        self._owned_fetcher = None  # lazily created default, closed by close()

    # -- pure, per-site (implement these) ---------------------------------- #
    @abstractmethod
    def search_url(self, query: str, page: int = 1) -> str:
        """URL of listing page ``page`` (1-based) for ``query``.

        Return the *same* URL as page 1 (or ``""``) when the source has no
        further pages — that is how a single-page source opts out of paging, and
        :meth:`search` stops without spending a request to find out.
        """

    @abstractmethod
    def parse_search(self, text: str) -> list[SearchHit]:
        """Extract listing hits from a search page's body."""

    @abstractmethod
    def parse_detail(self, text: str, hit: SearchHit) -> RawJob:
        """Extract a full :class:`RawJob` from a detail page's body."""

    # -- optional per-site hooks ------------------------------------------- #
    def matches_query(self, hit: SearchHit, query: str) -> bool:
        """Whether ``hit`` answers ``query``. True unless a source says otherwise.

        Search-backed sources have already applied the query server-side, so the
        default is to trust them. Feed-backed sources, which serve a fixed
        listing no matter what you ask for, override this — see
        :class:`jobpilot.crawler.feed.FeedScraper`.
        """
        return True

    def default_fetcher(self) -> Fetcher:
        """The fetcher to use when none was injected. Browser by default."""
        from jobpilot.crawler.fetch import PlaywrightFetcher

        return PlaywrightFetcher()

    # -- fetching ----------------------------------------------------------- #
    def _resolve_fetcher(self) -> Fetcher:
        if self.fetcher is not None:
            return self.fetcher
        if self._owned_fetcher is None:
            self._owned_fetcher = self.default_fetcher()
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

    # -- search: walk listing pages until we have enough -------------------- #
    def search(self, query: str = "", limit: int | None = None) -> list[SearchHit]:
        """Collect hits across listing pages, newest page first.

        Stops at the first of: ``limit`` hits collected, ``max_pages`` reached,
        a page with no hits, a page whose hits were all seen already, or a page
        URL identical to one already fetched.

        That "all seen already" check is the load-bearing one. A board that
        *accepts* ``?page=2`` and ignores it answers 200 with page 1 again, and
        without cross-page dedup the crawl would happily collect the same ten
        jobs five times and report a successful deep sweep. It is the same class
        of failure as TopCV silently dropping ``?keyword=`` (CLAUDE.md): the
        parameter is not rejected, it simply does nothing, so only the *content*
        can tell you the difference.
        """
        hits: list[SearchHit] = []
        kept_ids: set[str] = set()  # what we are returning
        seen_ids: set[str] = set()  # everything the site has shown us, relevant or not
        seen_urls: set[str] = set()

        for page in range(1, max(1, self.max_pages) + 1):
            url = self.search_url(query, page)
            if not url or url in seen_urls:
                break  # the source has no distinct URL for this page
            seen_urls.add(url)

            if page > 1:
                self.rate.wait()  # paging is still N requests at the site
            try:
                page_hits = self.parse_search(self._fetch(url))
            except Exception as exc:
                if page == 1:
                    raise  # the site itself failed — let the pipeline isolate it
                # Later pages are a bonus. Keep what we already have rather than
                # throwing away a good page 1 because page 3 timed out. The
                # reason is logged, not swallowed: "blocked — anti-bot" and
                # "timed out" call for different responses from whoever reads it.
                log.warning(
                    "[%s] page %d failed (%s), keeping %d hit(s)", self.source, page, exc, len(hits)
                )
                break

            page_ids = {h.native_id for h in page_hits if h.native_id}
            new = [
                h
                for h in page_hits
                if h.native_id and h.native_id not in kept_ids and self.matches_query(h, query)
            ]
            log.info(
                "[%s] page %d: %d hit(s), %d new+relevant",
                self.source,
                page,
                len(page_hits),
                len(new),
            )

            if not page_ids:
                if page > 1:
                    log.info("[%s] page %d is empty — end of results", self.source, page)
                break
            # Whether the *site* moved on is a separate question from whether we
            # wanted any of it. A general job board legitimately serves a whole
            # page with no Java on it, and page N+1 may be full of it — stopping
            # there would silently truncate the crawl. Only a page that repeats
            # ids we have already been shown proves the page parameter did
            # nothing, and that is the one worth abandoning.
            if page_ids <= seen_ids:
                log.warning(
                    "[%s] page %d repeated results already seen — the site is ignoring the "
                    "page parameter; stopping at %d hit(s)",
                    self.source,
                    page,
                    len(hits),
                )
                break

            seen_ids |= page_ids
            kept_ids.update(h.native_id for h in new)
            hits.extend(new)
            if limit is not None and len(hits) >= limit:
                break

        return hits

    # -- crawl loop (template method) -------------------------------------- #
    def crawl(self, query: str = "", limit: int | None = None) -> list[RawJob]:
        """Search, then fetch+parse up to ``limit`` detail pages.

        A search-page failure aborts this site (propagates to the pipeline,
        which isolates it). A single detail-page failure is logged and skipped
        so one bad posting never sinks the batch.
        """
        hits = self.search(query, limit)
        # A parser whose selectors stopped matching returns [] and the crawl then
        # reports success with nothing to show — the exact failure PLAN §10 calls
        # out ("cảnh báo khi 0 job"). It is indistinguishable from a genuinely
        # empty result set, so say so loudly instead of logging it as normal.
        if not hits:
            log.warning(
                "[%s] search parsed to 0 hits for query=%r — either the query "
                "has no results or the selectors no longer match the site",
                self.source,
                query,
            )
        elif limit is not None and len(hits) < limit:
            log.warning(
                "[%s] only %d hit(s) for query=%r, wanted %d — the source ran out of "
                "pages, or has fewer matching jobs than you asked for",
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
                detail = ""
                if self.needs_detail:
                    self.rate.wait()
                    detail = self._fetch(hit.url)
                results.append(self.parse_detail(detail, hit))
            except Exception as exc:
                log.warning("[%s] skip %s: %s", self.source, hit.url, exc)
                continue
        return results
