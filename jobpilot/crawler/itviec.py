"""ITviec scraper (PLAN §5.1 — the MVP priority source).

Search results expose each job URL via the ``data-search--job-selection-job-url``
Stimulus attribute (the documented ITviec mechanism); detail pages are parsed
with resilient CSS selectors + fallbacks. Selectors are best-effort and may need
tuning against live HTML — the unit tests pin the *parsing contract* against a
snapshot so regressions surface early.
"""

from __future__ import annotations

from urllib.parse import quote_plus, urljoin, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from jobpilot.crawler.base import BaseScraper
from jobpilot.crawler.text import clean_text
from jobpilot.crawler.types import RawJob, SearchHit

BASE_URL = "https://itviec.com"


def _text(el: Tag | None) -> str:
    return clean_text(el.get_text(" ", strip=True)) if el else ""


def _first(soup: BeautifulSoup, *selectors: str) -> Tag | None:
    for sel in selectors:
        found = soup.select_one(sel)
        if found is not None:
            return found
    return None


class ITViecScraper(BaseScraper):
    source = "itviec"

    def search_url(self, query: str) -> str:
        q = quote_plus(query or "java spring boot")
        return f"{BASE_URL}/it-jobs?query={q}"

    def _native_id(self, url: str) -> str:
        # ITviec job URLs look like /it-jobs/<slug>-<id>; the trailing slug is stable.
        slug = urlsplit(url).path.rstrip("/").split("/")[-1]
        return slug or url

    def parse_search(self, html: str) -> list[SearchHit]:
        soup = BeautifulSoup(html, "html.parser")
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for el in soup.select("[data-search--job-selection-job-url]"):
            href = el.get("data-search--job-selection-job-url")
            if not href:
                continue
            url = urljoin(BASE_URL, href)
            native_id = self._native_id(url)
            if native_id in seen:
                continue
            seen.add(native_id)
            hits.append(SearchHit(native_id=native_id, url=url, title=_text(el)[:200]))
        return hits

    def parse_detail(self, html: str, hit: SearchHit) -> RawJob:
        soup = BeautifulSoup(html, "html.parser")

        title = _text(_first(soup, "h1")) or hit.title
        company = _text(
            _first(soup, ".employer-name", ".company-name", "[class*=employer]", "[class*=company]")
        )
        location = _text(_first(soup, "[class*=location]", "[class*=city]")) or hit.location
        salary = _text(_first(soup, "[class*=salary]")) or hit.salary

        skills = []
        for tag in soup.select(".itag, [class*=tag-list] a, [class*=skill] a"):
            s = _text(tag)
            if s and s not in skills:
                skills.append(s)

        body = _first(
            soup,
            ".job-description",
            "#job-description",
            "[class*=job-description]",
            "[class*=job-content]",
            "main",
        )
        description_html = str(body) if body else ""

        return RawJob(
            source=self.source,
            native_id=hit.native_id,
            url=hit.url,
            title=title,
            company=company,
            location=location or None,
            salary=salary or None,
            posted_raw=_text(_first(soup, "[class*=posted]", "[class*=date]")) or None,
            skills=skills[:20],
            description_html=description_html,
            apply_channel="portal",  # ITviec applications happen on-site → human-in-the-loop
            apply_target=hit.url,
        )
