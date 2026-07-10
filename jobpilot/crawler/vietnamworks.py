"""VietnamWorks scraper — scaffold (PLAN §5.1).

VietnamWorks is a Next.js SPA; the full JD lives in the ``__NEXT_DATA__`` JSON
blob (de-hydration), so parsing means JSON extraction rather than DOM scraping.
Pending a real snapshot; disabled by default. Conforms to :class:`BaseScraper`
so filling ``parse_*`` + enabling in config is all that remains.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from jobpilot.crawler.base import BaseScraper
from jobpilot.crawler.types import RawJob, SearchHit

BASE_URL = "https://www.vietnamworks.com"


class VietnamWorksScraper(BaseScraper):
    source = "vietnamworks"

    def search_url(self, query: str) -> str:
        return f"{BASE_URL}/viec-lam?q={quote_plus(query or 'java')}"

    def parse_search(self, html: str) -> list[SearchHit]:  # pragma: no cover - scaffold
        raise NotImplementedError(
            "VietnamWorks parser pending a snapshot — parse __NEXT_DATA__ JSON (PLAN.md §5.1)."
        )

    def parse_detail(self, html: str, hit: SearchHit) -> RawJob:  # pragma: no cover - scaffold
        raise NotImplementedError(
            "VietnamWorks parser pending a snapshot — parse __NEXT_DATA__ JSON (PLAN.md §5.1)."
        )
