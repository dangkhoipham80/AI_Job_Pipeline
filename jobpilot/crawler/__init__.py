"""Job crawlers (Playwright + stealth). See PLAN.md §5.1.

Layout:
  * ``types``      — RawJob / SearchHit dataclasses (raw scraped shapes).
  * ``base``       — BaseScraper contract + the shared crawl loop.
  * ``fetch``      — PlaywrightFetcher (lazy; live network only).
  * ``ratelimit`` / ``robots`` — politeness (jittered delay, robots.txt).
  * ``text`` / ``normalize`` — HTML→md, level/score, RawJob → canonical Job.
  * ``persist``    — write + dedup (by id and by company/title).
  * ``pipeline``   — run scrapers → filter → persist → record Run (graceful).
  * ``registry``   — source key → scraper class; build enabled set from config.
  * ``itviec`` (real) / ``topcv`` / ``vietnamworks`` (scaffold) / ``fixture`` (offline).
"""

from jobpilot.crawler.base import BaseScraper, RobotsDisallowed
from jobpilot.crawler.normalize import NormalizedJob, normalize
from jobpilot.crawler.persist import CrawlStats, persist_jobs
from jobpilot.crawler.pipeline import RunReport, SiteReport, run_crawl
from jobpilot.crawler.registry import SCRAPERS, build_scrapers
from jobpilot.crawler.types import RawJob, SearchHit

__all__ = [
    "BaseScraper",
    "RobotsDisallowed",
    "RawJob",
    "SearchHit",
    "NormalizedJob",
    "normalize",
    "CrawlStats",
    "persist_jobs",
    "RunReport",
    "SiteReport",
    "run_crawl",
    "SCRAPERS",
    "build_scrapers",
]
