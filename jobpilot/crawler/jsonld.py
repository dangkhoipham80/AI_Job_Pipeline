"""schema.org ``JobPosting`` JSON-LD — the stable way to read a job board.

Both TopCV and VietnamWorks embed a full `JobPosting
<https://schema.org/JobPosting>`_ block for Google Jobs. That block is a far
better parsing target than their markup:

* **VietnamWorks** renders through styled-components, so every class is a build
  hash (``sc-1671001a-5 cjuZti``). Selectors written against those break on the
  site's next deploy, not on a redesign.
* **TopCV** hides the fields behind utility classes, the same shape that made
  ITviec's ``[class*=city]`` match ``opacity-50`` (CLAUDE.md "Bài học selector").
* The blocks carry an absolute ``datePosted`` instead of "3 ngày trước", and the
  complete JD instead of the truncated card blurb.

Google Jobs indexing depends on this staying correct, so the sites have a strong
incentive to keep it accurate — stronger than any incentive to keep a CSS class
name stable.

Pure functions: HTML string in, dataclass out. No network, no DB.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from jobpilot.crawler.text import clean_text

log = logging.getLogger(__name__)

# Salary "values" that are words rather than numbers — see `_amount`.
_NON_NUMERIC = re.compile(r"[^\d.,\s]")

_UNIT_SUFFIX = {
    "HOUR": "/hour",
    "DAY": "/day",
    "WEEK": "/week",
    "MONTH": "/month",
    "YEAR": "/year",
}


@dataclass
class JobPosting:
    """The subset of schema.org ``JobPosting`` JobPilot actually uses."""

    title: str = ""
    company: str = ""
    location: str | None = None
    salary: str | None = None
    posted_raw: str | None = None
    skills: list[str] = field(default_factory=list)
    description_html: str = ""
    employment_type: str | None = None
    # `identifier` is deliberately NOT exposed as a job id — see `_employer_id`.
    employer_id: str | None = None


# --------------------------------------------------------------------------- #
# locating the block
# --------------------------------------------------------------------------- #
def _candidates(node: object):
    """Yield every dict in a JSON-LD document, unwrapping lists and ``@graph``."""
    if isinstance(node, list):
        for item in node:
            yield from _candidates(item)
    elif isinstance(node, dict):
        yield node
        yield from _candidates(node.get("@graph", []))


def _is_job_posting(obj: dict) -> bool:
    t = obj.get("@type")
    types = t if isinstance(t, list) else [t]
    return any(isinstance(x, str) and x.lower() == "jobposting" for x in types)


def find_job_posting(html: str) -> dict | None:
    """The first ``JobPosting`` dict in any ``<script type=application/ld+json>``.

    Pages carry several JSON-LD blocks (``BreadcrumbList``, ``Organization``,
    ``WebSite``), sometimes several objects inside one block, so the type is
    matched rather than the position. A malformed block is skipped instead of
    aborting: one bad script tag should not cost us the whole posting.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        if "jobposting" not in raw.lower():
            continue
        try:
            doc = json.loads(raw)
        except (ValueError, TypeError) as exc:
            log.debug("skipping unparsable ld+json block: %s", exc)
            continue
        for obj in _candidates(doc):
            if _is_job_posting(obj):
                return obj
    return None


# --------------------------------------------------------------------------- #
# field extraction
# --------------------------------------------------------------------------- #
def _amount(value: object) -> float | None:
    """A salary figure, or ``None`` when the field holds a word.

    VietnamWorks puts the literal string ``"Thương lượng"`` ("negotiable") in
    ``baseSalary.value.value`` — a numeric slot — and pairs it with
    ``currency: USD, unitText: HOUR``. Coercing that would invent a salary of 0
    USD/hour, so anything that is not a plain number is refused. Same principle
    as ITviec's login-walled salary: no salary is the honest answer.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s or _NON_NUMERIC.search(s):
            return None
        try:
            return float(s.replace(",", "").replace(" ", ""))
        except ValueError:
            return None
    return None


def _fmt(n: float) -> str:
    return f"{int(n):,}" if float(n).is_integer() else f"{n:,.2f}"


def _salary(base: object) -> str | None:
    """``baseSalary`` → a human-readable string, or ``None`` if not disclosed."""
    if not isinstance(base, dict):
        return None
    currency = clean_text(str(base.get("currency") or "")) or ""

    node = base.get("value")
    if not isinstance(node, dict):
        # Some sites put the number directly on baseSalary.
        node = {"value": node, "unitText": base.get("unitText")}

    lo, hi = _amount(node.get("minValue")), _amount(node.get("maxValue"))
    single = _amount(node.get("value"))
    unit = str(node.get("unitText") or "").upper()
    suffix = _UNIT_SUFFIX.get(unit, "")

    if lo is not None and hi is not None:
        body = f"{_fmt(lo)} - {_fmt(hi)}"
    elif lo is not None or hi is not None:
        one = lo if lo is not None else hi
        body = f"from {_fmt(one)}" if lo is not None else f"up to {_fmt(hi)}"  # type: ignore[arg-type]
    elif single is not None:
        body = _fmt(single)
    else:
        return None  # nothing numeric → undisclosed / negotiable

    return clean_text(f"{body} {currency}{suffix}")


def _org_name(org: object) -> str:
    if isinstance(org, dict):
        return clean_text(str(org.get("name") or ""))
    if isinstance(org, str):
        return clean_text(org)
    return ""


def _place(place: object) -> str | None:
    """City from a ``Place``, preferring region over the ward/street detail.

    ``addressLocality`` is not reliably a city here: TopCV fills it with the ward
    ("Phường Xuân Đỉnh") and puts the city in ``addressRegion`` ("Hà Nội"), while
    VietnamWorks sets both to the city. Region first gets the city from both;
    locality-first would label half the TopCV jobs with a ward name.
    """
    if isinstance(place, list):
        parts = [p for p in (_place(x) for x in place) if p]
        # Multi-city postings: keep them all, deduped, order preserved.
        out: list[str] = []
        for p in parts:
            if p not in out:
                out.append(p)
        return ", ".join(out) or None
    if isinstance(place, str):
        return clean_text(place) or None
    if not isinstance(place, dict):
        return None

    addr = place.get("address")
    if isinstance(addr, str):
        return clean_text(addr) or None
    if isinstance(addr, dict):
        for key in ("addressRegion", "addressLocality"):
            val = clean_text(str(addr.get(key) or ""))
            if val:
                return val
    return clean_text(str(place.get("name") or "")) or None


def _skills(value: object) -> list[str]:
    """``skills`` → deduped list.

    The field is a free-form string in practice: VietnamWorks sends
    ``"Java, Python, MariaDB, Oracle, Java, MySQL"`` — comma-separated *with a
    repeat*, so dedup is required rather than cosmetic.
    """
    items: list[str] = []
    if isinstance(value, str):
        items = re.split(r"[,;·|/]|\n", value)
    elif isinstance(value, list):
        for x in value:
            if isinstance(x, str):
                items.extend(re.split(r"[,;·|/]|\n", x))
            elif isinstance(x, dict):
                items.append(str(x.get("name") or ""))

    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        s = clean_text(item)
        if not s or len(s) > 60:
            continue
        key = s.lower()
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _employer_id(obj: dict) -> str | None:
    """``identifier`` — which is the *employer*, not the job.

    Tempting and wrong as a ``native_id``. On TopCV the posting
    ``/viec-lam/business-analyst-domain-crm-contract/2254799.html`` reports
    ``identifier.value = 198409``, which is the company's own id (it matches
    ``/cong-ty/cong-ty-co-phan-misa/198409.html``), and ``identifier.name`` is
    the company name. VietnamWorks does the same. Keyed on that, every job from
    one employer would collapse into a single row and each crawl would overwrite
    the last. Job ids come from the URL — see each scraper's ``_native_id``.
    """
    ident = obj.get("identifier")
    if isinstance(ident, dict):
        val = ident.get("value")
        return clean_text(str(val)) or None if val is not None else None
    if isinstance(ident, (str, int)):
        return clean_text(str(ident)) or None
    return None


def parse_job_posting(html: str) -> JobPosting | None:
    """Read the page's ``JobPosting`` block, or ``None`` if it has none."""
    obj = find_job_posting(html)
    if obj is None:
        return None

    return JobPosting(
        title=clean_text(str(obj.get("title") or "")),
        company=_org_name(obj.get("hiringOrganization")),
        location=_place(obj.get("jobLocation")),
        salary=_salary(obj.get("baseSalary")),
        posted_raw=clean_text(str(obj.get("datePosted") or "")) or None,
        skills=_skills(obj.get("skills")),
        description_html=str(obj.get("description") or ""),
        employment_type=clean_text(str(obj.get("employmentType") or "")) or None,
        employer_id=_employer_id(obj),
    )
