"""Offline scraper over saved HTML — lets the full pipeline run without network.

``FixtureScraper`` parses a tiny, self-defined HTML format (not any real site)
served from an in-memory ``{url: html}`` map. It exercises
crawl → normalize → filter → dedup → persist → Run end-to-end on SQLite, and
gives live scrapers a reference for the ``BaseScraper`` contract.

Search page format::

    <a class="job" href="..." data-id="...">Job Title</a>

Detail page format::

    <h1>Title</h1>
    <div class="company">ACME</div>          <div class="location">HCM</div>
    <div class="salary">1000 USD</div>        <div class="posted">2 days ago</div>
    <span class="skill">Java</span> ...
    <div class="channel">portal</div>         <div class="target">hr@acme.com</div>
    <div class="jd"> ...JD html... </div>
"""

from __future__ import annotations

from bs4 import BeautifulSoup
from bs4.element import Tag

from jobpilot.crawler.base import BaseScraper
from jobpilot.crawler.text import clean_text
from jobpilot.crawler.types import RawJob, SearchHit

SEARCH_URL = "fixture://search"


def _text(el: Tag | None) -> str:
    return clean_text(el.get_text(" ", strip=True)) if el else ""


class FixtureScraper(BaseScraper):
    source = "fixture"

    def __init__(self, pages: dict[str, str], *, source: str = "fixture", **kwargs) -> None:
        super().__init__(**kwargs)
        self.source = source
        self._pages = pages
        if self.fetcher is None:
            self.fetcher = self._pages.__getitem__  # KeyError → skipped by crawl loop

    def search_url(self, query: str) -> str:
        return SEARCH_URL

    def parse_search(self, html: str) -> list[SearchHit]:
        soup = BeautifulSoup(html, "html.parser")
        hits: list[SearchHit] = []
        for a in soup.select("a.job"):
            url = a.get("href")
            if not url:
                continue
            hits.append(SearchHit(native_id=a.get("data-id") or url, url=url, title=_text(a)))
        return hits

    def parse_detail(self, html: str, hit: SearchHit) -> RawJob:
        soup = BeautifulSoup(html, "html.parser")
        jd = soup.select_one(".jd")
        return RawJob(
            source=self.source,
            native_id=hit.native_id,
            url=hit.url,
            title=_text(soup.select_one("h1")) or hit.title,
            company=_text(soup.select_one(".company")),
            location=_text(soup.select_one(".location")) or None,
            salary=_text(soup.select_one(".salary")) or None,
            posted_raw=_text(soup.select_one(".posted")) or None,
            skills=[_text(s) for s in soup.select(".skill") if _text(s)],
            description_html=str(jd) if jd else "",
            apply_channel=_text(soup.select_one(".channel")) or "portal",
            apply_target=_text(soup.select_one(".target")) or hit.url,
        )
