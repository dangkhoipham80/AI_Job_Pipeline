"""RawJob → canonical Job (PLAN §3.1) + filtering/scoring helpers.

Pure functions (no DB, no network). ``normalize`` produces a
:class:`NormalizedJob` carrying both the relational columns and the full JSONB
``payload``; ``persist.persist_jobs`` writes it. Timestamps use a fixed +07:00
offset (Asia/Ho_Chi_Minh, no DST) to avoid a tzdata dependency on Windows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from jobpilot.config import Config
from jobpilot.crawler.quality import Quality, flags_for, stack_coverage
from jobpilot.crawler.text import clean_text, dedup_key, html_to_markdown
from jobpilot.crawler.types import RawJob
from jobpilot.timeutil import VN_TZ, vn_now  # re-exported for callers/tests

__all__ = [
    "VN_TZ",
    "vn_now",
    "parse_posted_at",
    "infer_level",
    "stack_match_score",
    "title_excluded",
    "NormalizedJob",
    "normalize",
]


# --------------------------------------------------------------------------- #
# posted_at parsing
# --------------------------------------------------------------------------- #
_REL_EN = re.compile(r"(\d+)\s*(minute|hour|day|week|month)s?\s*ago")
_REL_VI = re.compile(r"(\d+)\s*(phút|giờ|ngày|tuần|tháng)\s*trước")
_UNIT_DAYS = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30}
_UNIT_SECONDS = {"minute": 60, "hour": 3600}
_VI_UNIT = {"phút": "minute", "giờ": "hour", "ngày": "day", "tuần": "week", "tháng": "month"}
_ABS_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y")
# Unix seconds: 1e9 is 2001, 1e11 is the year 5138 — wide enough for any real
# posting, narrow enough that a stray number is not mistaken for a timestamp.
_EPOCH_RE = re.compile(r"\d{9,11}")


def _delta_from(value: int, unit: str) -> timedelta:
    if unit in _UNIT_SECONDS:
        return timedelta(seconds=value * _UNIT_SECONDS[unit])
    return timedelta(days=value * _UNIT_DAYS[unit])


def parse_posted_at(raw: str | None, now: datetime | None = None) -> datetime | None:
    """Parse a site's posted-date string into a tz-aware datetime, or ``None``.

    Handles English/Vietnamese relative ("3 days ago", "2 giờ trước", "hôm
    qua") and absolute (dd/mm/yyyy, yyyy-mm-dd, ISO) forms.
    """
    if not raw:
        return None
    now = now or vn_now()
    s = clean_text(raw).lower()

    if any(k in s for k in ("just now", "vừa", "hôm nay", "today")):
        return now
    if any(k in s for k in ("hôm qua", "yesterday")):
        return now - timedelta(days=1)

    m = _REL_EN.search(s)
    if m:
        return now - _delta_from(int(m.group(1)), m.group(2))
    m = _REL_VI.search(s)
    if m:
        return now - _delta_from(int(m.group(1)), _VI_UNIT[m.group(2)])

    # Unix seconds, as JSON job APIs publish them. Bounded to 9-11 digits on
    # purpose: an unbounded int() would read a bare year ("2026") as an epoch
    # and date the job to January 1970, which is worse than not knowing.
    if _EPOCH_RE.fullmatch(s):
        return datetime.fromtimestamp(int(s), tz=VN_TZ)

    # ISO first (may carry its own tz), then day-first formats.
    try:
        dt = datetime.fromisoformat(s.replace("z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=VN_TZ)
    except ValueError:
        pass
    # RFC-822/2822 — what every RSS feed publishes ("Wed, 22 Jul 2026 07:00:51
    # +0000"). Without this a feed source lands with posted_at=None, which is not
    # a harmless gap: the job can never be flagged fresh (<48h), it drops out of
    # the dashboard's by-day chart, and freshness is the whole point of a feed.
    try:
        return parsedate_to_datetime(clean_text(raw))
    except (TypeError, ValueError):
        pass
    for fmt in _ABS_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=VN_TZ)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# level inference + matching
# --------------------------------------------------------------------------- #
# Seniority words, matched as whole words and in priority order (intern and
# fresher before senior, so "Senior mentor for interns" is not an internship).
#
# Whole words, not substrings: "intern" appears inside "internal" and
# "international", which every third JD says — that quietly filed Stripe's
# "Backend Engineer, AI Security" as an *internship*, and "leadership skills"
# made mid-level roles senior. Wrong data that looks right is the worst kind:
# it flows straight into the dashboard's level chart and the level filter.
#
# And bare "intern" counts only in the *title*: it is an ordinary word in prose
# ("we confer internally", German "beraten wir uns intern") but never an
# accident in a job title. "Internship"/"thực tập" are unambiguous anywhere.
_BARE_INTERN_RE = re.compile(r"\binterns?\b", re.I)
_LEVEL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("intern", r"\b(?:internships?|thực tập)\b"),
    ("fresher", r"\bfreshers?\b"),
    ("junior", r"\bjuniors?\b"),
    ("senior", r"\b(?:senior|lead|principal|staff)\b|trưởng nhóm"),
    ("middle", r"\b(?:middle|mid-level|mid level)\b"),
)
_LEVEL_RES = tuple((level, re.compile(pat, re.I)) for level, pat in _LEVEL_PATTERNS)


def infer_level(title: str, description: str = "") -> str | None:
    """Best-effort seniority from title/JD (intern/fresher checked before senior)."""
    if _BARE_INTERN_RE.search(title or ""):
        return "intern"
    text = f"{title} {description}"
    for level, pattern in _LEVEL_RES:
        if pattern.search(text):
            return level
    return None


def stack_match_score(haystack: str, stacks: list[str]) -> float:
    """Fraction of configured stacks mentioned in ``haystack`` (0..1)."""
    if not stacks:
        return 0.0
    hay = haystack.lower()
    hits = sum(1 for s in stacks if s.lower() in hay)
    return round(hits / len(stacks), 3)


def title_excluded(title: str, exclude_keywords: list[str]) -> bool:
    """True if the *title* contains any exclude keyword (case-insensitive).

    Matched against the title only — matching full JD over-excludes (a Java role
    may list ".NET" as a nice-to-have). Seniority exclusions (Senior/Lead) live
    here too via ``config.crawl.exclude_keywords``.
    """
    t = (title or "").lower()
    return any(kw.lower() in t for kw in exclude_keywords)


# --------------------------------------------------------------------------- #
# normalization
# --------------------------------------------------------------------------- #
def _fit(value: str | None, limit: int) -> str | None:
    """Clean ``value`` and clamp it to a column width, preserving ``None``.

    ``None`` must stay ``None`` — for ``salary`` it is the meaningful "not
    disclosed", and returning ``""`` would read as a published empty salary.
    """
    if value is None:
        return None
    cleaned = clean_text(value)
    return cleaned[:limit]


@dataclass
class NormalizedJob:
    id: str
    source: str
    url: str
    title: str
    company: str
    location: str | None
    salary: str | None
    level: str | None
    posted_at: datetime | None
    apply_channel: str | None
    apply_target: str | None
    match_score: float
    fresh: bool
    dedup_key: str
    payload: dict = field(default_factory=dict)


def normalize(raw: RawJob, cfg: Config, now: datetime | None = None) -> NormalizedJob:
    """Turn a scraped :class:`RawJob` into a persistable :class:`NormalizedJob`."""
    now = now or vn_now()
    desc_md = raw.description_md or html_to_markdown(raw.description_html)
    level = infer_level(raw.title, desc_md)
    posted_at = parse_posted_at(raw.posted_raw, now)
    fresh = bool(posted_at and (now - posted_at) <= timedelta(hours=cfg.crawl.fresh_hours))
    haystack = " ".join([raw.title, " ".join(raw.skills), desc_md])
    score = stack_match_score(haystack, cfg.crawl.stacks)
    # The same arithmetic the score comes from, reported instead of hidden: a
    # bare 0.25 is a verdict with no reasons attached.
    matched, missing = stack_coverage(haystack, cfg.crawl.stacks)
    quality = Quality(
        matched=matched,
        missing=missing,
        flags=flags_for(
            description_md=desc_md,
            posted_at=posted_at,
            needs_jd=bool(raw.extra.get("needs_jd")),
            now=now,
            stale_days=cfg.crawl.stale_days,
        ),
    )

    payload = {
        # Scraper-specific extras first, so a stray key can never shadow a
        # canonical PLAN §3.1 field. This is how flags like `needs_jd` survive.
        **raw.extra,
        "id": raw.id,
        "source": raw.source,
        "url": raw.url,
        "title": clean_text(raw.title),
        "company": clean_text(raw.company),
        "location": raw.location,
        "salary": raw.salary,
        "posted_at": posted_at.isoformat() if posted_at else None,
        "level": level,
        "skills": raw.skills,
        "description_md": desc_md,
        "apply_channel": raw.apply_channel,
        "apply_target": raw.apply_target,
        "raw_html_ref": raw.raw_ref,
        "crawled_at": now.isoformat(),
        "match_score": score,
        "is_fresh": fresh,
        "quality": quality.as_dict(),
    }
    return NormalizedJob(
        id=raw.id,
        source=raw.source,
        url=raw.url,
        # Clamped to the `jobs` column widths. A scraper that grabs too much is a
        # scraper bug, but on Postgres an overlong value raises
        # StringDataRightTruncation mid-flush and rolls back the *whole* crawl —
        # one bad field costing every job in the batch. Truncating keeps the
        # damage local and visible (payload still holds the full text), which is
        # the graceful-per-site-failure rule applied per field. SQLite ignores
        # these widths, so only a real Postgres run ever surfaces it.
        title=_fit(raw.title, 256),
        company=_fit(raw.company, 256),
        location=_fit(raw.location, 256),
        salary=_fit(raw.salary, 128),
        level=level,
        posted_at=posted_at,
        apply_channel=raw.apply_channel,
        apply_target=raw.apply_target,
        match_score=score,
        fresh=fresh,
        dedup_key=dedup_key(raw.company, raw.title),
        payload=payload,
    )
