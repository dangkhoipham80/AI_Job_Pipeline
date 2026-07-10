"""RawJob → canonical Job (PLAN §3.1) + filtering/scoring helpers.

Pure functions (no DB, no network). ``normalize`` produces a
:class:`NormalizedJob` carrying both the relational columns and the full JSONB
``payload``; ``persist.persist_jobs`` writes it. Timestamps use a fixed +07:00
offset (Asia/Ho_Chi_Minh, no DST) to avoid a tzdata dependency on Windows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from jobpilot.config import Config
from jobpilot.crawler.text import clean_text, dedup_key, html_to_markdown
from jobpilot.crawler.types import RawJob

VN_TZ = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh (no DST)


def vn_now() -> datetime:
    """Current time in Vietnam (tz-aware)."""
    return datetime.now(VN_TZ)


# --------------------------------------------------------------------------- #
# posted_at parsing
# --------------------------------------------------------------------------- #
_REL_EN = re.compile(r"(\d+)\s*(minute|hour|day|week|month)s?\s*ago")
_REL_VI = re.compile(r"(\d+)\s*(phút|giờ|ngày|tuần|tháng)\s*trước")
_UNIT_DAYS = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30}
_UNIT_SECONDS = {"minute": 60, "hour": 3600}
_VI_UNIT = {"phút": "minute", "giờ": "hour", "ngày": "day", "tuần": "week", "tháng": "month"}
_ABS_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y")


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

    # ISO first (may carry its own tz), then day-first formats.
    try:
        dt = datetime.fromisoformat(s.replace("z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=VN_TZ)
    except ValueError:
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
def infer_level(title: str, description: str = "") -> str | None:
    """Best-effort seniority from title/JD (intern/fresher checked before senior)."""
    text = f"{title} {description}".lower()
    if any(w in text for w in ("intern", "internship", "thực tập")):
        return "intern"
    if "fresher" in text:
        return "fresher"
    if "junior" in text:
        return "junior"
    if any(w in text for w in ("senior", " lead", "principal", "staff", "trưởng nhóm")):
        return "senior"
    if any(w in text for w in ("middle", "mid-level", "mid level")):
        return "middle"
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

    payload = {
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
    }
    return NormalizedJob(
        id=raw.id,
        source=raw.source,
        url=raw.url,
        title=clean_text(raw.title)[:256],
        company=clean_text(raw.company)[:256],
        location=raw.location,
        salary=raw.salary,
        level=level,
        posted_at=posted_at,
        apply_channel=raw.apply_channel,
        apply_target=raw.apply_target,
        match_score=score,
        fresh=fresh,
        dedup_key=dedup_key(raw.company, raw.title),
        payload=payload,
    )
