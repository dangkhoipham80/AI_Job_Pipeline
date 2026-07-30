"""ITviec scraper (PLAN §5.1 — the MVP priority source).

Search results are Stimulus-controlled cards; each carries the job's slug in a
``data-search--job-selection-*`` attribute (see ``SLUG_ATTR``). Detail pages are
parsed with resilient CSS selectors + fallbacks. Selectors are best-effort and
track a site that does rename things — the unit tests pin the *parsing contract*
against a snapshot of real HTML so a rename surfaces as a failing test rather
than as a crawl that silently returns nothing.
"""

from __future__ import annotations

from urllib.parse import quote_plus, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from jobpilot.crawler.base import BaseScraper
from jobpilot.crawler.text import el_text, first_match, leaf_texts
from jobpilot.crawler.types import RawJob, SearchHit
from jobpilot.crawler.vietnam import CITIES, find_city, find_posted, find_salary

BASE_URL = "https://itviec.com"

# The Stimulus value that identifies a job card. ITviec renamed this from
# `data-search--job-selection-job-url` (which held a full href) to a slug value;
# keeping the name in one constant means the next rename is a one-line fix.
SLUG_ATTR = "data-search--job-selection-job-slug-value"

__all__ = ["ITViecScraper", "BASE_URL", "SLUG_ATTR", "CITIES"]


def _company(card: Tag) -> str:
    """The employer name, from the first company link that actually has text.

    Every card links to the company twice: once wrapping the logo image (no
    text) and once on the name. Taking ``select_one`` blindly gets the logo and
    an empty string.
    """
    for link in card.select('a[href*="/companies/"]'):
        name = el_text(link)
        if name:
            return name
    return ""


def _location(card: Tag) -> str | None:
    """The city, matched by content rather than by class name.

    ITviec's cards are built from utility classes (``ips-4``, ``text-rich-grey``)
    with no semantic hook for the location, and matching class *substrings* is
    actively dangerous here: ``[class*=city]`` matches ``opacity-50`` and quietly
    returns whatever that element says. Vietnamese job locations are a small
    closed set, so recognising the value is both simpler and more stable than
    guessing at the markup around it — see :mod:`jobpilot.crawler.vietnam`, which
    now holds that closed set for every VN source.
    """
    return find_city(leaf_texts(card, max_len=40))


def _posted(card: Tag) -> str | None:
    """ "Posted 8 hours ago" / "3 days ago" — again matched on shape, not class."""
    return find_posted(leaf_texts(card, max_len=40))


def _salary(root: Tag) -> str | None:
    """A salary only if one is actually published.

    ITviec shows "Sign in to view salary" to logged-out visitors, and JobPilot
    stays logged out. Returning None is the honest answer — the alternative is
    every ITviec job appearing to disclose a salary it never did.
    """
    return find_salary(leaf_texts(root, max_len=60))


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
        """Read the result cards.

        Each card is a Stimulus controller carrying the job's slug in
        ``data-search--job-selection-job-slug-value``. That attribute is the
        anchor for everything else here: it is the only identifier on the card
        that is neither a rotating UUID (``data-job-key``, which changes between
        sessions and so would defeat dedup) nor a tracked URL full of
        ``click_source`` query junk.

        The card already carries title, company, location and skills, so those
        are read here and passed forward — the detail page can then only add to
        them, and a posting whose detail fetch fails still has a usable row.
        """
        soup = BeautifulSoup(html, "html.parser")
        hits: list[SearchHit] = []
        seen: set[str] = set()

        for card in soup.select(f"[{SLUG_ATTR}]"):
            slug = (card.get(SLUG_ATTR) or "").strip()
            if not slug or slug in seen:
                continue
            seen.add(slug)

            hits.append(
                SearchHit(
                    native_id=slug,
                    url=f"{BASE_URL}/it-jobs/{slug}",
                    title=el_text(first_match(card, "h3", "h2", "h4"))[:200],
                    company=_company(card),
                    location=_location(card),
                    posted_raw=_posted(card),
                )
            )
        return hits

    def parse_detail(self, html: str, hit: SearchHit) -> RawJob:
        soup = BeautifulSoup(html, "html.parser")

        title = el_text(first_match(soup, "h1")) or hit.title
        # The card is the trusted source for these three. The detail page only
        # fills a gap: its markup is the same class soup as the cards, and the
        # loose selectors that used to read it here returned page furniture —
        # `[class*=city]` matching `opacity-50` gave every job the location
        # "Hiring", and `[class*=salary]` picked up a promo banner.
        company = hit.company or el_text(first_match(soup, ".employer-name", ".company-name"))
        location = hit.location or _location(soup)
        salary = hit.salary or _salary(soup)

        skills = []
        for tag in soup.select(".itag, [class*=tag-list] a, [class*=skill] a"):
            s = el_text(tag)
            if s and s not in skills:
                skills.append(s)

        body = first_match(
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
            posted_raw=el_text(first_match(soup, "[class*=posted]", "[class*=date]")) or None,
            skills=skills[:20],
            description_html=description_html,
            apply_channel="portal",  # ITviec applications happen on-site → human-in-the-loop
            apply_target=hit.url,
        )
