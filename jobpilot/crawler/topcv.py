"""TopCV scraper (PLAN §5.1 — tier-1 source).

Contrary to the original scaffold note, TopCV is **not** a Vue SPA: the search
page and the job pages are server-rendered, so a plain fetch already carries all
50 result cards. The detail pages additionally embed a complete schema.org
``JobPosting`` block, which is what ``parse_detail`` reads (see
:mod:`jobpilot.crawler.jsonld` for why that beats the markup).

``robots.txt`` allows both paths used here — it only disallows CV-editor and
private-profile routes (``/cv/…``, ``/xem-cv/``, ``/sua-cv/``, ``/private/``).

Applying happens behind a TopCV login, so ``apply_channel`` is ``portal``:
human-in-the-loop, never auto-submitted (principle 2).
"""

from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup
from bs4.element import Tag

from jobpilot.crawler.base import BaseScraper
from jobpilot.crawler.jsonld import parse_job_posting
from jobpilot.crawler.text import clean_text, el_text, first_match, strip_query
from jobpilot.crawler.types import RawJob, SearchHit
from jobpilot.crawler.vietnam import clean_city, parse_salary

BASE_URL = "https://www.topcv.vn"

# The result card. `data-job-id` on the same element is TopCV's own numeric job
# id — stable across sessions, unlike the `u_sr_id` token in the href.
CARD_SELECTOR = ".job-item-search-result"
JOB_ID_ATTR = "data-job-id"

# /viec-lam/<slug>/<id>.html
_URL_ID_RE = re.compile(r"/viec-lam/[^/]+/(\d+)\.html")

# The one tag group that describes the work rather than perks or entry criteria.
_SPECIALTY_GROUP_RE = re.compile(r"chuyên môn|specialit|skill", re.I)

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _slug(query: str) -> str:
    """ "Java Spring Boot" → "java-spring-boot" for the search path.

    Vietnamese diacritics are folded to ASCII (TopCV's own slugs are ASCII), and
    anything else collapses to a single hyphen so a stray character cannot break
    the path.
    """
    folded = unicodedata.normalize("NFD", query.lower())
    ascii_only = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    return _SLUG_STRIP_RE.sub("-", ascii_only).strip("-") or "java"


def _title_anchor(card: Tag) -> Tag | None:
    """The heading anchor, preferring the titled heading over any other.

    ``first_match`` rather than ``select_one("h3.title a, h3 a")``: the latter
    resolves by document order, so a promo/"recently viewed" widget rendered
    inside the card ahead of the real heading would supply the title *and* the
    URL, storing the row under the wrong id.
    """
    return first_match(card, "h3.title a", "h3 a")


def _card_title(card: Tag) -> str:
    """The job title, without the promo badges that share its heading.

    ``h3.title`` also contains a ``.box-label-top`` block of labels, so reading
    the heading's text yields "Tin mới Nổi bật Business Analyst (…)". The inner
    anchor's ``span[title]`` holds exactly the title, and the anchor text is the
    fallback if that attribute goes away.
    """
    anchor = _title_anchor(card)
    if anchor is None:
        return ""
    span = anchor.select_one("span[title]")
    if span is not None:
        title = clean_text(str(span.get("title") or "")) or el_text(span)
        if title:
            return title
    return el_text(anchor)


def _card_company(card: Tag) -> str:
    """Employer name, preferring the tooltip attribute over the visible text.

    The visible ``.company-name`` is CSS-truncated for long names while the
    ``title`` attribute carries it in full.
    """
    el = card.select_one("a.company .company-name, .company-name")
    if el is None:
        return ""
    return clean_text(str(el.get("title") or "")) or el_text(el)


def _card_location(card: Tag) -> str | None:
    """City from ``.city-text``.

    Read the inner span, never ``label.address[title]``: that attribute holds an
    escaped HTML blob (a notice about the 2025 administrative renaming plus a
    ``<ul>`` of wards), which is not a location.
    """
    return clean_city(el_text(card.select_one("label.address .city-text, .city-text")))


class TopCVScraper(BaseScraper):
    source = "topcv"

    def search_url(self, query: str) -> str:
        """``/tim-viec-lam-<slug>`` — the keyword goes in the *path*.

        ``/tim-viec-lam-it?keyword=java`` looks like a search and is not one:
        TopCV ignores the query string and serves the generic IT category. It
        answers 200 with 50 cards, so nothing looks broken — but they are 1,655
        assorted IT jobs ("IT Support", "IT Comtor", "Unity Developer") instead of
        the 84 Java ones, and every single one is then dropped by the stack filter
        for scoring 0. A silently-ignored parameter is worse than an error: the
        crawl reports success and quietly delivers the wrong jobs.
        """
        return f"{BASE_URL}/tim-viec-lam-{_slug(query or 'java')}"

    def _native_id(self, card_id: str, url: str) -> str:
        """TopCV's numeric job id, from the card attribute or the URL path."""
        if card_id:
            return card_id
        m = _URL_ID_RE.search(url)
        return m.group(1) if m else strip_query(url)

    def parse_search(self, html: str) -> list[SearchHit]:
        """Read the server-rendered result cards.

        The card already carries title, company, city, salary and required
        experience, so all of it is passed forward: a posting whose detail fetch
        fails still lands as a usable row.
        """
        soup = BeautifulSoup(html, "html.parser")
        hits: list[SearchHit] = []
        seen: set[str] = set()

        for card in soup.select(CARD_SELECTOR):
            anchor = _title_anchor(card)
            href = clean_text(str(anchor.get("href") or "")) if anchor else ""
            if not href:
                continue
            url = strip_query(href if href.startswith("http") else f"{BASE_URL}{href}")
            native_id = self._native_id(clean_text(str(card.get(JOB_ID_ATTR) or "")), url)
            if not native_id or native_id in seen:
                continue
            seen.add(native_id)

            experience = el_text(card.select_one("label.exp"))
            hits.append(
                SearchHit(
                    native_id=native_id,
                    url=url,
                    title=_card_title(card)[:200],
                    company=_card_company(card),
                    location=_card_location(card),
                    # "Thoả thuận" is a non-answer, so parse_salary returns None.
                    salary=parse_salary(
                        el_text(card.select_one("label.title-salary, label.salary"))
                    ),
                    extra={"experience": experience} if experience else {},
                )
            )
        return hits

    def parse_detail(self, html: str, hit: SearchHit) -> RawJob:
        """Prefer the page's ``JobPosting`` JSON-LD; fall back to the DOM.

        The JSON-LD ``description`` is the whole JD (Mô tả công việc + Yêu cầu
        ứng viên + Quyền lợi), which is what the tailor step needs — the DOM
        equivalent, ``.box-job-information-detail``, is only the fallback.
        """
        soup = BeautifulSoup(html, "html.parser")
        posting = parse_job_posting(html)

        title = (posting.title if posting else "") or el_text(soup.select_one("h1")) or hit.title
        company = (
            hit.company
            or (posting.company if posting else "")
            or el_text(soup.select_one("a.name, .company-name"))
        )
        # The card's city beats the JSON-LD address, which mixes in ward/street.
        location = hit.location or clean_city(posting.location if posting else None)

        # Salary comes only from sources that unambiguously belong to *this* job:
        # its own search card, or the page's baseSalary. There is deliberately no
        # scan of the detail body — `.box-job-information-detail` also contains
        # TopCV's "việc làm tương tự" panel, whose sibling cards carry their own
        # salaries once the page hydrates, so scanning it attributed a neighbour's
        # figure to this job (two unrelated roles both came back "20 - 60 triệu").
        # When neither source publishes one, None is the honest answer — the same
        # call as ITviec's login-walled salary.
        salary = hit.salary or (posting.salary if posting else None)

        skills = list(posting.skills) if posting else []
        if not skills:
            skills = self._dom_skills(soup)

        description_html = (posting.description_html if posting else "") or str(
            soup.select_one(".box-job-information-detail") or ""
        )

        return RawJob(
            source=self.source,
            native_id=hit.native_id,
            url=hit.url,
            title=title,
            company=company,
            location=location,
            salary=salary,
            posted_raw=(posting.posted_raw if posting else None) or hit.posted_raw,
            skills=skills[:20],
            description_html=description_html,
            # Carry the card's extras forward — `normalize` spreads `raw.extra`
            # into the payload, and only RawJob.extra reaches it. Dropping it here
            # silently lost the required-experience label off every TopCV job.
            extra=dict(hit.extra),
            # TopCV applications need a logged-in TopCV account → user submits.
            apply_channel="portal",
            apply_target=hit.url,
        )

    @staticmethod
    def _dom_skills(soup: BeautifulSoup) -> list[str]:
        """Tags from the "Chuyên môn" group only, deduped, order kept.

        TopCV renders three sibling tag groups with identical markup — "Yêu cầu"
        (2 năm kinh nghiệm, Đại Học trở lên), "Quyền lợi" (Bảo hiểm xã hội, Team
        building, Du lịch hàng năm) and "Chuyên môn". Selecting the tags without
        reading their group label makes "Team building" a *skill*, which then
        feeds ``match_score`` and shows up in the tailor gap report as something
        the CV is missing. Only the specialty group is about the work.
        """
        skills: list[str] = []
        for group in soup.select(".job-tags__group"):
            label = el_text(group.select_one(".job-tags__group-name"))
            if not _SPECIALTY_GROUP_RE.search(label):
                continue
            for tag in group.select(".job-tags__group-list-tag a, .job-tags__group-list-tag span"):
                s = el_text(tag)
                if s and s not in skills:
                    skills.append(s)
        return skills
