"""ATS adapters — one scraper covering many company career pages (PLAN §5.1.1 tier 3).

Most companies don't build a job board; they rent one. Greenhouse and Lever each
publish a documented JSON endpoint per customer, so a single adapter reaches
every company on that platform — "thêm nguồn = thêm 1 dòng config" taken to its
conclusion: adding a *company* is one word in a list.

This is also where the good jobs are. A role usually appears on the employer's
own careers page before it reaches an aggregator, and some never leave it.

**A "page" here is a company.** The shared paging loop asks ``search_url`` for
page 1, 2, 3… and stops when the URLs run out, which is exactly "walk the
configured boards in order". Nothing about the loop needed changing; the only
override is ``max_pages``, because `crawl.max_pages` exists to stop us walking
an *unbounded* board forever and a hand-written list of companies is already
bounded by the person who wrote it.

``robots.txt`` (checked against :class:`~jobpilot.crawler.robots.RobotsPolicy`,
not by eye):

* ``boards-api.greenhouse.io`` disallows only ``/embed/`` — the board endpoint is
  fine.
* ``api.lever.co`` is ``Allow: /`` with ``Crawl-delay: 1``; the crawler's 2-5s
  limiter already exceeds that.
* **Ashby is deliberately absent.** ``api.ashbyhq.com`` serves no robots.txt at
  all (401) while its sibling ``jobs.ashbyhq.com`` disallows ``/api/``. That is
  the same shape as VietnamWorks' internal XHR host, which this project also
  declined to call — it needs an explicit decision, not a default.

Applying always happens on the employer's own form, so ``apply_channel`` is
``external``: JobPilot hands you the link and you submit (principle 2).
"""

from __future__ import annotations

import html
import logging
import re
from urllib.parse import quote

from jobpilot.crawler.feed import FeedScraper, load_json
from jobpilot.crawler.text import clean_text
from jobpilot.crawler.types import RawJob, SearchHit

log = logging.getLogger(__name__)


class AtsScraper(FeedScraper):
    """Base for board-per-company ATS APIs. Each configured board is one page."""

    #: Board tokens (the company's slug on that ATS).
    boards: tuple[str, ...] = ()

    def __init__(self, *, boards: list[str] | None = None, **kw) -> None:
        super().__init__(**kw)
        if boards is not None:
            self.boards = tuple(b.strip() for b in boards if b and b.strip())
        # One page per company: the config ceiling is about unbounded boards,
        # and this list is already bounded by whoever typed it.
        self.max_pages = max(1, len(self.boards))

    def board_url(self, board: str) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def search_url(self, query: str, page: int = 1) -> str:
        if not 1 <= page <= len(self.boards):
            return ""
        return self.board_url(self.boards[page - 1])

    def search(self, query: str = "", limit: int | None = None) -> list[SearchHit]:
        """Say "no companies configured" plainly instead of "0 hits".

        Without this the shared loop reports the generic zero-results warning,
        which reads as "the parser broke" — a misleading thing to tell someone
        whose only mistake is not having filled in a list yet.
        """
        if not self.boards:
            log.info(
                "[%s] no company boards configured — add tokens under `ats.%s` in "
                "config.yaml (the slug in the careers-page URL)",
                self.source,
                self.source,
            )
            return []
        return super().search(query, limit)

    def match_haystack(self, hit: SearchHit) -> str:
        """Title plus the ATS's own department/team labels."""
        return f"{hit.title} {' '.join(hit.extra.get('tags') or [])}"


# --------------------------------------------------------------------------- #
# Greenhouse
# --------------------------------------------------------------------------- #
GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseScraper(AtsScraper):
    source = "greenhouse"

    def board_url(self, board: str) -> str:
        # `content=true` returns the full description inline, which is what makes
        # this a one-request-per-company source instead of one-per-job.
        return f"{GREENHOUSE_API}/{quote(board)}/jobs?content=true"

    def parse_search(self, text: str) -> list[SearchHit]:
        data = load_json(text)
        if not isinstance(data, dict):
            raise ValueError(f"expected a Greenhouse board object, got {type(data).__name__}")

        hits: list[SearchHit] = []
        for job in data.get("jobs") or []:
            native_id = clean_text(str(job.get("id") or ""))
            url = clean_text(str(job.get("absolute_url") or ""))
            title = clean_text(str(job.get("title") or ""))
            if not native_id or not url or not title:
                continue
            hits.append(
                SearchHit(
                    native_id=native_id,
                    url=url,
                    title=title[:200],
                    company=clean_text(str(job.get("company_name") or "")),
                    location=clean_text(str((job.get("location") or {}).get("name") or "")) or None,
                    # `first_published` is when the role opened; `updated_at` moves
                    # every time a recruiter edits a typo and would make an old
                    # posting look brand new.
                    posted_raw=clean_text(
                        str(job.get("first_published") or job.get("updated_at") or "")
                    )
                    or None,
                    extra={"tags": _greenhouse_tags(job), "job": job},
                )
            )
        return hits

    def parse_detail(self, text: str, hit: SearchHit) -> RawJob:
        job = dict(hit.extra.get("job") or {})
        return RawJob(
            source=self.source,
            native_id=hit.native_id,
            url=hit.url,
            title=hit.title,
            company=hit.company,
            location=hit.location,
            salary=None,  # Greenhouse boards don't publish one.
            posted_raw=hit.posted_raw,
            skills=list(hit.extra.get("tags") or [])[:20],
            # The API double-encodes: `content` arrives as "&lt;div&gt;…", so
            # storing it raw shows the reader literal tags instead of the JD.
            description_html=html.unescape(str(job.get("content") or "")),
            apply_channel="external",
            apply_target=hit.url,
            extra={"ats": "greenhouse", "requisition_id": str(job.get("requisition_id") or "")},
        )


def _greenhouse_tags(job: dict) -> list[str]:
    """Department and office names — the only categorisation the board carries."""
    out: list[str] = []
    for key in ("departments", "offices"):
        for item in job.get(key) or []:
            name = clean_text(str((item or {}).get("name") or ""))
            if name and name not in out:
                out.append(name)
    return out


# --------------------------------------------------------------------------- #
# Lever
# --------------------------------------------------------------------------- #
LEVER_API = "https://api.lever.co/v0/postings"
# hostedUrl is https://jobs.lever.co/<company>/<uuid>
_LEVER_COMPANY_RE = re.compile(r"jobs\.lever\.co/([^/]+)/")


class LeverScraper(AtsScraper):
    source = "lever"

    def board_url(self, board: str) -> str:
        return f"{LEVER_API}/{quote(board)}?mode=json"

    def parse_search(self, text: str) -> list[SearchHit]:
        data = load_json(text)
        if not isinstance(data, list):
            # A wrong/expired board token answers 404 with an object, not a list.
            raise ValueError(f"expected a Lever posting array, got {type(data).__name__}")

        hits: list[SearchHit] = []
        for job in data:
            native_id = clean_text(str(job.get("id") or ""))
            url = clean_text(str(job.get("hostedUrl") or ""))
            title = clean_text(str(job.get("text") or ""))
            if not native_id or not url or not title:
                continue
            categories = job.get("categories") or {}
            hits.append(
                SearchHit(
                    native_id=native_id,
                    url=url,
                    title=title[:200],
                    # Lever's payload never names the employer — only the board
                    # does, and the board slug is in the URL of every posting.
                    company=_lever_company(url),
                    location=clean_text(str(categories.get("location") or "")) or None,
                    posted_raw=_ms_to_epoch_seconds(job.get("createdAt")),
                    extra={"tags": _lever_tags(categories), "job": job},
                )
            )
        return hits

    def parse_detail(self, text: str, hit: SearchHit) -> RawJob:
        job = dict(hit.extra.get("job") or {})
        return RawJob(
            source=self.source,
            native_id=hit.native_id,
            url=hit.url,
            title=hit.title,
            company=hit.company,
            location=hit.location,
            salary=None,
            posted_raw=hit.posted_raw,
            skills=list(hit.extra.get("tags") or [])[:20],
            description_html=_lever_description(job),
            apply_channel="external",
            apply_target=hit.url,
            extra={
                "ats": "lever",
                "workplace_type": clean_text(str(job.get("workplaceType") or "")),
            },
        )


def _lever_company(url: str) -> str:
    match = _LEVER_COMPANY_RE.search(url)
    return match.group(1).replace("-", " ").title() if match else ""


def _lever_tags(categories: dict) -> list[str]:
    out: list[str] = []
    for key in ("team", "department", "commitment"):
        value = clean_text(str(categories.get(key) or ""))
        if value and value not in out:
            out.append(value)
    return out


def _lever_description(job: dict) -> str:
    """The whole posting, not just the intro.

    Lever splits a job across ``description`` (the pitch), ``lists`` (the actual
    requirements and responsibilities) and ``additional`` (benefits). Keeping
    only ``description`` hands the tailor a company blurb with none of the
    requirements the CV has to answer — the same mistake as reading
    VietnamWorks' JSON-LD description and losing "Yêu cầu công việc".
    """
    parts = [str(job.get("description") or "")]
    for block in job.get("lists") or []:
        text = clean_text(str((block or {}).get("text") or ""))
        content = str((block or {}).get("content") or "")
        if text:
            parts.append(f"<h3>{html.escape(text)}</h3>")
        if content:
            parts.append(f"<ul>{content}</ul>")
    parts.append(str(job.get("additional") or ""))
    return "".join(p for p in parts if p)


def _ms_to_epoch_seconds(value) -> str | None:
    """Lever timestamps are milliseconds; ``parse_posted_at`` reads seconds.

    Converted here rather than by widening the epoch guard: that guard accepts
    9-11 digits precisely so a stray 13-digit number is *not* mistaken for a
    date, and loosening it to please one source would give that protection away
    for every other source.
    """
    try:
        return str(int(value) // 1000)
    except (TypeError, ValueError):
        return None
