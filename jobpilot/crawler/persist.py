"""Write normalized jobs to Postgres with dedup (PLAN §3.2).

Two dedup layers:
  1. **Primary** — ``Job.id = <source>:<native_id>`` (the PK). Re-seeing a job
     refreshes its scraped fields but never touches its ``status`` (it may
     already be shortlisted/applied).
  2. **Cross-source** — ``(company, normalized_title)``. The same role posted on
     two boards is inserted once; later sightings within ``dedup_days`` are
     skipped so the dashboard/Slack aren't spammed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.crawler.normalize import NormalizedJob, vn_now
from jobpilot.crawler.text import dedup_key
from jobpilot.store.models import Job, JobStatus


@dataclass
class CrawlStats:
    fetched: int = 0  # raw jobs scraped (pre-filter)
    inserted: int = 0  # new rows
    updated: int = 0  # existing id refreshed
    duplicates: int = 0  # cross-source dupes skipped
    filtered: int = 0  # dropped by stack/exclude rules
    fresh: int = 0  # posted within crawl.fresh_hours
    errors: int = 0

    def merge(self, other: CrawlStats) -> None:
        for f in ("fetched", "inserted", "updated", "duplicates", "filtered", "fresh", "errors"):
            setattr(self, f, getattr(self, f) + getattr(other, f))

    def as_dict(self) -> dict:
        return {
            "fetched": self.fetched,
            "inserted": self.inserted,
            "updated": self.updated,
            "duplicates": self.duplicates,
            "filtered": self.filtered,
            "fresh": self.fresh,
            "errors": self.errors,
        }


def _new_job(nj: NormalizedJob, run_id: int | None = None) -> Job:
    return Job(
        run_id=run_id,
        id=nj.id,
        source=nj.source,
        url=nj.url,
        title=nj.title,
        company=nj.company,
        location=nj.location,
        salary=nj.salary,
        level=nj.level,
        posted_at=nj.posted_at,
        status=JobStatus.DISCOVERED,
        match_score=nj.match_score,
        apply_channel=nj.apply_channel,
        apply_target=nj.apply_target,
        payload=nj.payload,
    )


def _refresh(job: Job, nj: NormalizedJob) -> None:
    """Refresh scraped fields on re-crawl; leave ``status`` untouched."""
    job.url = nj.url
    job.title = nj.title
    job.company = nj.company
    job.location = nj.location
    job.salary = nj.salary
    job.level = nj.level
    job.posted_at = nj.posted_at
    job.match_score = nj.match_score
    job.apply_channel = nj.apply_channel
    job.apply_target = nj.apply_target
    job.payload = nj.payload


def persist_jobs(
    session: Session,
    jobs: list[NormalizedJob],
    *,
    dedup_days: int = 14,
    now: datetime | None = None,
    run_id: int | None = None,
) -> CrawlStats:
    """Insert/refresh ``jobs``; skip cross-source dupes seen within ``dedup_days``.

    Flushes (does not commit) — the caller owns the transaction boundary.
    """
    now = now or vn_now()
    stats = CrawlStats()
    cutoff = now - timedelta(days=dedup_days)

    # Preload recent cross-source keys so we don't re-add the same role.
    seen_keys: set[str] = set()
    for company, title in session.execute(
        select(Job.company, Job.title).where(Job.crawled_at >= cutoff)
    ):
        seen_keys.add(dedup_key(company, title))

    for nj in jobs:
        existing = session.get(Job, nj.id)
        if existing is not None:
            _refresh(existing, nj)
            stats.updated += 1
            if nj.fresh:
                stats.fresh += 1
            continue
        if nj.dedup_key in seen_keys:
            stats.duplicates += 1
            continue
        session.add(_new_job(nj, run_id=run_id))
        seen_keys.add(nj.dedup_key)
        stats.inserted += 1
        if nj.fresh:
            stats.fresh += 1

    session.flush()
    return stats
