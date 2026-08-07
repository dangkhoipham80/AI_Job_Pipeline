"""We Work Remotely scraper (PLAN §5.1.1 — tier-2, official RSS).

WWR publishes a real RSS feed per category, and ``robots.txt`` allows
everything except account/admin routes. That makes it the cleanest source in
the project: no browser, no anti-bot, no HTML archaeology, and the feed carries
the **entire** job description — so one request yields 25-130 complete jobs.

Two shapes worth knowing:

* There is **no search feed**. ``/remote-jobs/search.rss?term=java`` answers 406.
  So the query is applied locally (:class:`~jobpilot.crawler.feed.FeedScraper`),
  and "paging" means walking the next *category* feed rather than page 2 —
  which is exactly what :meth:`BaseScraper.search` already does, since it only
  asks ``search_url`` for a URL and stops when the URLs repeat.
* The ``<title>`` is ``"Company: Job Title"``. Storing it whole would put the
  employer's name inside every job title, break the ``(company, title)``
  cross-source dedup key, and hand the tailor a title it would echo back.
"""

from __future__ import annotations

import re

from jobpilot.crawler.feed import FeedScraper, parse_rss_items
from jobpilot.crawler.text import clean_text, html_to_markdown, strip_query
from jobpilot.crawler.types import RawJob, SearchHit

BASE_URL = "https://weworkremotely.com"

# Category feeds, most specific first so a limited crawl spends its budget on
# the closest match. Walked one per "page" by the shared search loop.
FEEDS = (
    "remote-back-end-programming-jobs",
    "remote-full-stack-programming-jobs",
    "remote-programming-jobs",
    "remote-front-end-programming-jobs",
    "remote-devops-sysadmin-jobs",
)

# /remote-jobs/<slug> — the slug is the stable id; WWR publishes no numeric one.
_SLUG_RE = re.compile(r"/remote-jobs/([^/?#]+)")

# Leading decoration on a title ("🌍 Location Services Engineer"). Anything that
# is not alphanumeric and not the start of a tech name (".NET", "#", "C++").
_TITLE_JUNK_RE = re.compile(r"^[^\w.#+]+", re.UNICODE)


def split_company_title(raw: str) -> tuple[str, str]:
    """``"Gusto, Inc.: Business Money Engineering"`` → ``("Gusto, Inc.", "…")``.

    Splits on the *first* ``": "`` only. Roles do contain colons
    ("Engineer: Platform"), and splitting on the last one would file the job
    under a company called "Gusto, Inc.: Engineer".

    A title with no colon is returned whole with an empty company rather than
    guessed at — a missing company shows as missing, a wrong one does not.
    """
    text = clean_text(raw)
    company, sep, title = text.partition(": ")
    if not sep:
        return "", text
    return company.strip(), _TITLE_JUNK_RE.sub("", title.strip())


class WeWorkRemotelyScraper(FeedScraper):
    source = "weworkremotely"

    def search_url(self, query: str, page: int = 1) -> str:
        """The ``page``-th category feed, or ``""`` once they run out."""
        if not 1 <= page <= len(FEEDS):
            return ""
        return f"{BASE_URL}/categories/{FEEDS[page - 1]}.rss"

    def match_haystack(self, hit: SearchHit) -> str:
        """Title plus WWR's own category ("Back-End Programming")."""
        return f"{hit.title} {hit.extra.get('category', '')}"

    def parse_search(self, text: str) -> list[SearchHit]:
        hits: list[SearchHit] = []
        for item in parse_rss_items(text):
            url = strip_query(clean_text(item.get("link") or item.get("guid") or ""))
            match = _SLUG_RE.search(url)
            if not match:
                continue
            company, title = split_company_title(item.get("title", ""))
            if not title:
                continue
            hits.append(
                SearchHit(
                    native_id=match.group(1),
                    url=url,
                    title=title[:200],
                    company=company,
                    # "Anywhere in the World", "USA Only", "Europe Only" — a
                    # remote *eligibility* region, which is what a location means
                    # on this board.
                    location=clean_text(item.get("region")) or None,
                    posted_raw=clean_text(item.get("pubDate")) or None,
                    extra={
                        "category": clean_text(item.get("category")),
                        # The feed is the whole job; parse_detail reads it from
                        # here instead of fetching the page again.
                        "description_html": item.get("description", ""),
                    },
                )
            )
        return hits

    def parse_detail(self, text: str, hit: SearchHit) -> RawJob:
        """Build the job from the feed item — ``needs_detail`` is False.

        ``text`` is empty by design: the crawl loop never fetched a detail page,
        because RSS already delivered the full description.
        """
        extra = dict(hit.extra)
        description_html = extra.pop("description_html", "")
        return RawJob(
            source=self.source,
            native_id=hit.native_id,
            url=hit.url,
            title=hit.title,
            company=hit.company,
            location=hit.location,
            # WWR does not publish salary in the feed. None is the honest answer.
            salary=None,
            posted_raw=hit.posted_raw,
            description_html=description_html,
            # The listing links to the employer's own form; WWR is a board, not
            # an applicant tracker. You submit it (principle 2).
            apply_channel="external",
            apply_target=hit.url,
            extra=extra,
        )

    @staticmethod
    def description_md(hit: SearchHit) -> str:
        """The item's description as markdown — exposed for tests/debugging."""
        return html_to_markdown(hit.extra.get("description_html", ""))
