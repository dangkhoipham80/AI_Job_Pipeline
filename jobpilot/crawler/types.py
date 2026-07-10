"""Raw crawl data types — the un-normalized shapes scrapers emit.

A scraper's ``parse_search`` yields :class:`SearchHit` (enough to open a detail
page); ``parse_detail`` yields :class:`RawJob` (everything scraped from a job
page, still site-shaped). ``normalize.normalize`` turns a ``RawJob`` into the
canonical PLAN §3.1 Job schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SearchHit:
    """A single result on a search/listing page — enough to fetch the detail page."""

    native_id: str
    url: str
    title: str = ""
    company: str = ""
    location: str | None = None
    salary: str | None = None
    posted_raw: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class RawJob:
    """Everything a scraper pulled from a job detail page (pre-normalization)."""

    source: str
    native_id: str
    url: str
    title: str = ""
    company: str = ""
    location: str | None = None
    salary: str | None = None
    posted_raw: str | None = None  # e.g. "2 days ago", "08/07/2026", "hôm qua"
    skills: list[str] = field(default_factory=list)
    description_html: str = ""
    description_md: str = ""
    apply_channel: str | None = None  # email | portal | external
    apply_target: str | None = None  # hr@acme.com | https://apply-url
    raw_ref: str | None = None  # path to cached raw HTML (audit)
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Global dedup key: ``<source>:<native_id>`` (PLAN §3.1)."""
        return f"{self.source}:{self.native_id}"
