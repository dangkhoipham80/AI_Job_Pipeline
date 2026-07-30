"""TopCV scraper — scaffold (PLAN §5.1).

TopCV is a Vue SPA; the parsing contract can't be pinned without a real HTML
snapshot, so ``parse_*`` raise until one is captured. The class already conforms
to :class:`BaseScraper`, so enabling it in ``config.yaml`` + filling these two
methods is all that's left. Disabled by default; an enabled-but-unfilled source
fails its site gracefully in the pipeline.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from jobpilot.crawler.base import BaseScraper
from jobpilot.crawler.types import RawJob, SearchHit

BASE_URL = "https://www.topcv.vn"


class TopCVScraper(BaseScraper):
    source = "topcv"

    def search_url(self, query: str) -> str:
        return f"{BASE_URL}/tim-viec-lam-it?keyword={quote_plus(query or 'java')}"

    def parse_search(self, html: str) -> list[SearchHit]:  # pragma: no cover - scaffold
        raise NotImplementedError(
            "TopCV parser pending a real HTML snapshot — see PLAN.md §5.1 (Vue SPA)."
        )

    def parse_detail(self, html: str, hit: SearchHit) -> RawJob:  # pragma: no cover - scaffold
        raise NotImplementedError(
            "TopCV parser pending a real HTML snapshot — see PLAN.md §5.1 (Vue SPA)."
        )
