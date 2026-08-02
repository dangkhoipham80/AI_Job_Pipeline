"""Source key → scraper class, and building the enabled set from config.

Adding a site = register its class here + one line in ``config.yaml`` (PLAN
§5.1.1 "thêm nguồn = thêm 1 scraper + 1 dòng config").
"""

from __future__ import annotations

import logging

from jobpilot.config import Config
from jobpilot.crawler.base import BaseScraper, Fetcher
from jobpilot.crawler.arbeitnow import ArbeitnowScraper
from jobpilot.crawler.itviec import ITViecScraper
from jobpilot.crawler.linkedin import LinkedInAlertsScraper
from jobpilot.crawler.ratelimit import RateLimiter
from jobpilot.crawler.robots import RobotsPolicy
from jobpilot.crawler.topcv import TopCVScraper
from jobpilot.crawler.vietnamworks import VietnamWorksScraper
from jobpilot.crawler.weworkremotely import WeWorkRemotelyScraper

log = logging.getLogger(__name__)

SCRAPERS: dict[str, type[BaseScraper]] = {
    # -- tier 1: Vietnamese job boards ------------------------------------- #
    "itviec": ITViecScraper,
    # Reads your mailbox for LinkedIn Job Alerts — never crawls LinkedIn.
    "linkedin": LinkedInAlertsScraper,
    "topcv": TopCVScraper,
    "vietnamworks": VietnamWorksScraper,
    # -- tier 2: official feeds (no browser, no anti-bot) ------------------ #
    "arbeitnow": ArbeitnowScraper,
    "weworkremotely": WeWorkRemotelyScraper,
}


def build_scrapers(
    cfg: Config,
    *,
    fetcher: Fetcher | None = None,
    respect_robots: bool = True,
    only: list[str] | None = None,
) -> list[BaseScraper]:
    """Instantiate scrapers for every enabled+known source in config.

    ``fetcher`` overrides every scraper's own choice and exists for tests, which
    inject an offline map. Leave it ``None`` in production: each scraper then
    picks the right transport for its source, and a browser session shared with
    a feed source would hand its parser ``<pre>``-wrapped JSON. Rate limit,
    paging depth and robots policy come from config.

    ``only`` narrows the set for a single run without touching config — that is
    how the dashboard lets you crawl one site without disabling the others. It
    can only *subtract*: a source disabled in config stays disabled, so the
    Settings page remains the one place that decides what may run at all.
    """
    from jobpilot.crawler.fetch import DEFAULT_USER_AGENT

    low, high = cfg.crawl.rate_limit_seconds
    scrapers: list[BaseScraper] = []
    wanted = {k.strip().lower() for k in only} if only else None
    for src in cfg.enabled_sources():
        if wanted is not None and src.key.lower() not in wanted:
            continue
        cls = SCRAPERS.get(src.key)
        if cls is None:
            log.warning("no scraper registered for source %r — skipping", src.key)
            continue
        scrapers.append(
            cls(
                fetcher=fetcher,
                rate_limiter=RateLimiter(low, high),
                robots=RobotsPolicy(DEFAULT_USER_AGENT) if respect_robots else None,
                max_pages=cfg.crawl.max_pages,
            )
        )
    return scrapers
