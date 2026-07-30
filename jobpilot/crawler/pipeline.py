"""Crawl orchestration: run scrapers → filter → normalize → persist → record Run.

Each site is isolated: a scraper that throws (Cloudflare, DOM change, robots)
is logged, marked failed in its :class:`SiteReport`, and the crawl continues
(PLAN §5.1 "graceful per-site fail"). One ``runs`` row captures the whole batch
for the dashboard's Runs page.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from jobpilot.config import Config
from jobpilot.crawler.base import BaseScraper
from jobpilot.crawler.normalize import normalize, title_excluded, vn_now
from jobpilot.crawler.persist import CrawlStats, persist_jobs
from jobpilot.store.models import Run

log = logging.getLogger(__name__)


@dataclass
class SiteReport:
    source: str
    ok: bool
    stats: CrawlStats
    error: str | None = None


@dataclass
class RunReport:
    run_id: int | None
    sites: list[SiteReport] = field(default_factory=list)

    @property
    def totals(self) -> CrawlStats:
        total = CrawlStats()
        for s in self.sites:
            total.merge(s.stats)
        return total


def default_query(cfg: Config) -> str:
    """Search query derived from configured stacks (first few, joined)."""
    stacks = cfg.crawl.stacks[:3]
    return " ".join(stacks) if stacks else "backend developer"


def _crawl_site(
    scraper: BaseScraper,
    cfg: Config,
    session: Session,
    query: str,
    now: datetime,
    dedup_days: int,
    run_id: int | None = None,
    limit_override: int | None = None,
) -> SiteReport:
    limit = limit_override or cfg.crawl.jobs_per_site
    raws = scraper.crawl(query, limit=limit)

    kept = []
    filtered = 0
    for raw in raws:
        nj = normalize(raw, cfg, now)
        excluded = title_excluded(raw.title, cfg.crawl.exclude_keywords)
        no_stack = bool(cfg.crawl.stacks) and nj.match_score <= 0.0
        if excluded or no_stack:
            filtered += 1
            continue
        kept.append(nj)

    stats = persist_jobs(session, kept, dedup_days=dedup_days, now=now, run_id=run_id)
    stats.fetched = len(raws)
    stats.filtered = filtered
    log.info(
        "[%s] fetched=%d inserted=%d updated=%d dup=%d filtered=%d fresh=%d",
        scraper.source,
        stats.fetched,
        stats.inserted,
        stats.updated,
        stats.duplicates,
        stats.filtered,
        stats.fresh,
    )
    return SiteReport(source=scraper.source, ok=True, stats=stats)


def run_crawl(
    scrapers: list[BaseScraper],
    cfg: Config,
    session: Session,
    *,
    query: str | None = None,
    now: datetime | None = None,
    dedup_days: int = 14,
    record_run: bool = True,
    limit: int | None = None,
) -> RunReport:
    """Crawl every scraper into ``session`` and return a :class:`RunReport`.

    Commits once at the end. Individual site failures never abort the batch.

    ``limit`` overrides ``cfg.crawl.jobs_per_site`` for this run only — useful
    for a one-off deep sweep without editing the config.
    """
    now = now or vn_now()
    query = query if query is not None else default_query(cfg)

    run: Run | None = None
    if record_run:
        run = Run(kind="crawl", stats={})
        session.add(run)
        session.flush()  # assign run.id

    report = RunReport(run_id=run.id if run else None)
    for scraper in scrapers:
        try:
            report.sites.append(
                _crawl_site(scraper, cfg, session, query, now, dedup_days, report.run_id, limit)
            )
        except Exception as exc:
            log.exception("[%s] crawl failed", scraper.source)
            report.sites.append(
                SiteReport(scraper.source, ok=False, stats=CrawlStats(errors=1), error=str(exc))
            )
        finally:
            scraper.close()

    if run is not None:
        run.finished_at = now
        run.stats = {
            "query": query,
            "totals": report.totals.as_dict(),
            "sites": {
                s.source: {"ok": s.ok, "error": s.error, **s.stats.as_dict()} for s in report.sites
            },
        }
    session.commit()
    return report
