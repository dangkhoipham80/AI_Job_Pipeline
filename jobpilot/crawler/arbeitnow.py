"""Arbeitnow scraper (PLAN §5.1.1 — tier-2, official JSON job-board API).

Arbeitnow publishes a documented free API, and unlike the other remote feeds
tried for this phase its ``robots.txt`` actually permits it (verified against
:class:`~jobpilot.crawler.robots.RobotsPolicy`, not by eye — see CLAUDE.md
"Nguồn tier-2 đã loại" for the ones that don't).

What it is, and what it isn't:

* **Really paginated.** ``?page=N`` returns a genuinely different set — page 1
  and page 2 share zero slugs (verified live), and running off the end answers
  200 with an empty ``data`` list. That makes it the one tier-2 source that
  exercises the shared paging loop rather than opting out of it.
* **No search parameter.** The API serves the newest jobs, all trades. So
  relevance is applied locally by :class:`~jobpilot.crawler.feed.FeedScraper`
  against the title and Arbeitnow's own tags — never against the description,
  which on any real posting name-drops half the industry.
* **A German board.** Expect Germany/EU roles and German-language descriptions
  alongside English ones. Titles are usually in English for tech roles.

Their ``meta.terms`` asks that the API not be abused and that consumers link
back. The crawl's rate limiter and ``max_pages`` ceiling cover the first;
``apply_target`` pointing at the original posting covers the second. Applying
happens on the employer's own form and ``robots.txt`` disallows the apply route,
so ``apply_channel`` is ``external``: you submit it (principle 2).
"""

from __future__ import annotations

import logging

from jobpilot.crawler.feed import FeedScraper, parse_json_feed
from jobpilot.crawler.text import clean_text
from jobpilot.crawler.types import RawJob, SearchHit

log = logging.getLogger(__name__)

API_URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowScraper(FeedScraper):
    source = "arbeitnow"

    def search_url(self, query: str, page: int = 1) -> str:
        """``?page=N``. The API takes no query — filtering happens locally."""
        return f"{API_URL}?page={max(1, page)}"

    def match_haystack(self, hit: SearchHit) -> str:
        """Title plus Arbeitnow's own tags ("Engineering", "R&D : Databases")."""
        tags = hit.extra.get("tags") or []
        return f"{hit.title} {' '.join(str(t) for t in tags)}"

    def parse_search(self, text: str) -> list[SearchHit]:
        data = parse_json_feed(text)
        hits: list[SearchHit] = []
        for job in data.get("data") or []:
            # The slug is the id Arbeitnow itself uses in the URL; there is no
            # numeric one. Never fall back to the URL — a tracked URL would
            # change between crawls and defeat dedup.
            native_id = clean_text(str(job.get("slug") or ""))
            url = clean_text(str(job.get("url") or ""))
            title = clean_text(str(job.get("title") or ""))
            if not native_id or not url or not title:
                continue
            hits.append(
                SearchHit(
                    native_id=native_id,
                    url=url,
                    title=title[:200],
                    company=clean_text(str(job.get("company_name") or "")),
                    location=_location(job),
                    # Unix seconds. parse_posted_at understands them; without
                    # that the job would never count as fresh.
                    posted_raw=clean_text(str(job.get("created_at") or "")) or None,
                    extra={"tags": job.get("tags") or [], "job": job},
                )
            )
        return hits

    def parse_detail(self, text: str, hit: SearchHit) -> RawJob:
        """Build the job from the feed record — ``needs_detail`` is False."""
        job = dict(hit.extra.get("job") or {})
        return RawJob(
            source=self.source,
            native_id=hit.native_id,
            url=hit.url,
            title=hit.title,
            company=hit.company,
            location=hit.location,
            # Arbeitnow publishes no salary field. None is the honest answer.
            salary=None,
            posted_raw=hit.posted_raw,
            # Tags are categories ("Engineering"), not a skills list — but they
            # are what this source knows, and normalize scores against the JD too.
            skills=[clean_text(str(t)) for t in (job.get("tags") or []) if str(t).strip()][:20],
            description_html=str(job.get("description") or ""),
            apply_channel="external",
            apply_target=hit.url,
            extra={
                "job_types": [clean_text(str(t)) for t in (job.get("job_types") or [])],
                "remote": bool(job.get("remote")),
                # Their terms ask for a link back; the payload records the source.
                "source_name": "Arbeitnow",
            },
        )


def _location(job: dict) -> str | None:
    """The posting's location, or "Remote" when that is all it says.

    ``location`` is often "Homeoffice" on this board, which is a work
    arrangement rather than a place — but it is still the most specific thing
    published, so it is kept as-is rather than blanked or upgraded to a city
    nobody stated.
    """
    location = clean_text(str(job.get("location") or ""))
    if location:
        return location
    return "Remote" if job.get("remote") else None
