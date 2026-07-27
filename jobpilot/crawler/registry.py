"""Source key → scraper class, and building the enabled set from config.

Adding a site = register its class here + one line in ``config.yaml`` (PLAN
§5.1.1 "thêm nguồn = thêm 1 scraper + 1 dòng config").
"""

from __future__ import annotations

import logging

from jobpilot.config import Config
from jobpilot.crawler.base import BaseScraper, Fetcher
from jobpilot.crawler.itviec import ITViecScraper
from jobpilot.crawler.linkedin import LinkedInAlertsScraper
from jobpilot.crawler.ratelimit import RateLimiter
from jobpilot.crawler.robots import RobotsPolicy
from jobpilot.crawler.topcv import TopCVScraper
from jobpilot.crawler.vietnamworks import VietnamWorksScraper

log = logging.getLogger(__name__)

SCRAPERS: dict[str, type[BaseScraper]] = {
    "itviec": ITViecScraper,
    # Reads your mailbox for LinkedIn Job Alerts — never crawls LinkedIn.
    "linkedin": LinkedInAlertsScraper,
    "topcv": TopCVScraper,
    "vietnamworks": VietnamWorksScraper,
}


def build_scrapers(
    cfg: Config,
    *,
    fetcher: Fetcher | None = None,
    respect_robots: bool = True,
) -> list[BaseScraper]:
    """Instantiate scrapers for every enabled+known source in config.

    A single ``fetcher`` (e.g. one Playwright session) can be shared across all
    scrapers. Rate limit + robots policy come from config.
    """
    from jobpilot.crawler.fetch import DEFAULT_USER_AGENT

    low, high = cfg.crawl.rate_limit_seconds
    scrapers: list[BaseScraper] = []
    for src in cfg.enabled_sources():
        cls = SCRAPERS.get(src.key)
        if cls is None:
            log.warning("no scraper registered for source %r — skipping", src.key)
            continue
        scrapers.append(
            cls(
                fetcher=fetcher,
                rate_limiter=RateLimiter(low, high),
                robots=RobotsPolicy(DEFAULT_USER_AGENT) if respect_robots else None,
            )
        )
    return scrapers
