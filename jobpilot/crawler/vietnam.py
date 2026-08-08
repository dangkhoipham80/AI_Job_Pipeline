"""Recognising Vietnamese job-board values by *content*, not by markup.

The hard-won lesson from ITviec (CLAUDE.md "Bài học selector"): these boards are
built from utility or hashed CSS classes, so matching class names — especially by
substring — reads page furniture. ``[class*=city]`` matched ``opacity-50`` and
gave every job the location "Hiring"; ``[class*=salary]`` matched an "IT Salary
Report" banner.

Vietnamese job fields are small closed sets, so recognising the *value* is both
simpler and survives redesigns. Shared by every VN scraper so the city list and
the "negotiable" vocabulary exist once.
"""

from __future__ import annotations

import re

from jobpilot.crawler.text import clean_text

# All 34 provinces/cities after the 2025 administrative merger, plus "Remote".
# Exhaustive on purpose: an unlisted province yields `location=None`, which is
# indistinguishable from "remote/unspecified" once it reaches the dashboard. The
# live crawl surfaced exactly that — an FPT Software job in Khánh Hòa.
CITIES: tuple[str, ...] = (
    # Vietnamese spellings (what TopCV/VietnamWorks render)
    "Hồ Chí Minh",
    "Hà Nội",
    "Đà Nẵng",
    "Cần Thơ",
    "Hải Phòng",
    "Huế",
    "An Giang",
    "Bắc Ninh",
    "Cà Mau",
    "Cao Bằng",
    "Điện Biên",
    "Đắk Lắk",
    "Đồng Nai",
    "Đồng Tháp",
    "Gia Lai",
    "Hà Tĩnh",
    "Hưng Yên",
    "Khánh Hòa",
    "Lai Châu",
    "Lâm Đồng",
    "Lạng Sơn",
    "Lào Cai",
    "Nghệ An",
    "Ninh Bình",
    "Phú Thọ",
    "Quảng Ngãi",
    "Quảng Ninh",
    "Quảng Trị",
    "Sơn La",
    "Tây Ninh",
    "Thái Nguyên",
    "Thanh Hóa",
    "Tuyên Quang",
    "Vĩnh Long",
    # Cities still commonly named in postings though merged into a province.
    "Nha Trang",
    "Bình Dương",
    "Vũng Tàu",
    "Biên Hòa",
    # ASCII/English spellings (ITviec renders these)
    "Ho Chi Minh",
    "Ha Noi",
    "Hanoi",
    "Da Nang",
    "Can Tho",
    "Hai Phong",
    "Binh Duong",
    "Dong Nai",
    "Bac Ninh",
    "Quang Ninh",
    "Khanh Hoa",
    "Thai Nguyen",
    "Hue",
    "Remote",
)

# Words that may sit beside a city name without changing what it is, so that
# "TP. Hồ Chí Minh" and "Hue City" still read as one city. "mới"/"cũ" belong here
# as well as in `_CITY_SUFFIX_RE`: that one is anchored to end-of-string, so in a
# multi-city label like "Hà Nội (mới), Hồ Chí Minh" the annotation sits mid-string
# and survives — without this the whole label failed to read as a location.
_CITY_FILLER_RE = re.compile(
    r"\b(tp|t\.p|thành phố|city|province|tỉnh|việt nam|vietnam|vn|mới|new|cũ|old)\b|[.,\-–()/]",
    re.I,
)

# Cities may arrive as a list: "Hà Nội, Hồ Chí Minh".
_CITY_SPLIT_RE = re.compile(r"[,;/]| và | and ", re.I)

# "Thoả thuận" (TopCV) / "Thương lượng" (VietnamWorks) / "Cạnh tranh" all mean
# "we are not telling you". Storing them as the salary would make every such job
# look like it disclosed one, so they normalise to None.
_NEGOTIABLE = (
    "thoả thuận",
    "thỏa thuận",
    "thương lượng",
    "cạnh tranh",
    "negotiable",
    "competitive",
)

# A login wall, which is different: it means the number exists but is hidden from
# us, so scanning must *stop* rather than adopt a number found further down the
# page (ITviec's "IT Salary Report" banner sits right there). See `find_salary`.
_HIDDEN = (
    "sign in to view salary",
    "đăng nhập để xem",
)

_UNDISCLOSED = _NEGOTIABLE + _HIDDEN

# A salary is only a salary if a number is attached to money words.
_SALARY_RE = re.compile(
    r"(\$|usd|vnd|triệu|million|tr\b)\s*[\d,.]|[\d,.]+\s*(-|đến|to)?\s*[\d,.]*\s*(usd|vnd|triệu|million)",
    re.I,
)

# "Cập nhật hôm nay", "3 ngày trước", "Posted 8 hours ago", "30/07/2026".
# "ago"/"trước" stay OPTIONAL: ITviec's cards have rendered bare durations
# ("8 hours") where space is tight, and requiring the suffix silently dropped the
# timestamp — the job then looked undated rather than fresh.
_POSTED_RE = re.compile(
    r"\b(just now|today|yesterday|hôm nay|hôm qua|vừa xong"
    r"|\d+\s*(minute|hour|day|week|month)s?(\s*ago)?"
    r"|\d+\s*(phút|giờ|ngày|tuần|tháng)(\s*trước)?"
    r"|\d{1,2}/\d{1,2}/\d{4})",
    re.I,
)

# Social-proof and "show more" chrome that sits in the same text run as the real
# fields. LinkedIn's "34 company alumni" leaking into `location` was exactly this
# bug (CLAUDE.md), and VietnamWorks cards carry the same shape in Vietnamese.
_NOISE_RE = re.compile(
    r"^(\+\d+|\||•|·|mới|new|urgent|hot|nổi bật|tin mới|gấp"
    r"|rất đông ứng viên|hãy là .*ứng viên.*|\d+\s*(ứng viên|applicants?)"
    r"|xem thêm|show more)$",
    re.I,
)

# TopCV appends this after cities that were renamed by the 2025 administrative
# merge ("Hồ Chí Minh (mới)"). It annotates the *label*, not the place.
_CITY_SUFFIX_RE = re.compile(r"\s*\((mới|new|cũ|old)\)\s*$", re.I)


def is_noise(text: str) -> bool:
    """True for badge/social-proof/"+3" chrome that must never become a field."""
    return bool(_NOISE_RE.match(clean_text(text)))


def clean_city(text: str | None) -> str | None:
    """Strip the "(mới)" administrative-rename annotation from a city label."""
    s = clean_text(text)
    return _CITY_SUFFIX_RE.sub("", s).strip() or None


def _is_one_city(part: str) -> bool:
    """True only if ``part`` is a city name and (almost) nothing else.

    A bare case-insensitive substring test is not enough. "Remote" is in the
    list, so ``"remote" in "remote debugging".lower()`` would label a skill tag
    as the job's location — and unlike a missing location, wrong data looks
    right. So the city has to *account for* the text: remove the matched name and
    only filler ("TP.", "City", punctuation) may remain.
    """
    low = clean_text(part).lower()
    if not low:
        return False
    # Abbreviations and unaccented spellings first, because they are exact.
    # Without this the gate and the canonicaliser knew different vocabularies:
    # ``canonical_city("TPHCM")`` answered "Hồ Chí Minh" while this returned
    # False, so the pipeline dropped it — and the unit test still passed,
    # because it called the canonicaliser directly and never the path
    # production takes.
    if _fold_city(low) in _CITY_ALIASES:
        return True
    for city in CITIES:
        name = city.lower()
        if name not in low:
            continue
        if not _CITY_FILLER_RE.sub(" ", low.replace(name, " ")).strip():
            return True
    return False


def looks_like_city(text: str) -> bool:
    """True if every comma-separated part of ``text`` names a city.

    Requiring *all* parts to be cities is what keeps "Hà Nội, Hồ Chí Minh"
    (a genuine multi-city posting) while rejecting "Java, Remote debugging".
    """
    cleaned = clean_city(text)
    if not cleaned:
        return False
    parts = [p for p in (p.strip() for p in _CITY_SPLIT_RE.split(cleaned)) if p]
    return bool(parts) and all(_is_one_city(p) for p in parts)


def find_city(texts: list[str] | tuple[str, ...]) -> str | None:
    """First text that names a known city, cleaned. ``None`` if none does."""
    for text in texts:
        if text and looks_like_city(text):
            return clean_city(text)
    return None


def looks_like_posted(text: str) -> bool:
    return bool(_POSTED_RE.search(text or ""))


def find_posted(texts: list[str] | tuple[str, ...]) -> str | None:
    for text in texts:
        if looks_like_posted(text):
            return clean_text(text)
    return None


def is_undisclosed_salary(text: str | None) -> bool:
    low = clean_text(text).lower()
    return any(word in low for word in _UNDISCLOSED)


# A published salary is a label, not a paragraph. "20 - 60 triệu VND/month" and
# "$ 1,500-2,500 /tháng" are the shapes; anything much longer is a block of page
# text that merely happens to contain a number.
MAX_SALARY_LEN = 80


def parse_salary(text: str | None) -> str | None:
    """A salary string, or ``None`` when the board is withholding it.

    A stated figure wins over a "negotiable" word in the *same* label: TopCV
    writes things like "Cạnh tranh từ 15-25 triệu", and checking the word first
    threw away a range the employer did publish. Only a label with no figure at
    all counts as withheld.

    The length guard is what keeps a caller that hands over a whole JD from
    getting the whole JD back as the "salary" — that happened, and because the
    column is ``VARCHAR(128)`` it aborted the entire crawl transaction on
    Postgres rather than spoiling one field.
    """
    s = clean_text(text)
    if not s or len(s) > MAX_SALARY_LEN:
        return None
    return s if _SALARY_RE.search(s) else None


def find_salary(texts: list[str] | tuple[str, ...]) -> str | None:
    """First disclosed salary among ``texts``.

    A **login wall** stops the scan: the number exists but is hidden from us, so
    adopting one found further down the page (ITviec's "IT Salary Report" banner)
    would attribute a stranger's figure to this job.

    A **"negotiable"** label does not stop it. It usually sits in a perks blurb
    ("Competitive salary package") that can precede the real figure in document
    order, and hard-stopping there discarded a salary the job did publish.
    """
    for text in texts:
        if any(word in clean_text(text).lower() for word in _HIDDEN):
            return None
        found = parse_salary(text)
        if found:
            return found
    return None


#: Spellings that mean the same city. Keys are ASCII-folded; the value is the
#: canonical label shown in charts. Without this a "top cities" chart lists
#: "Hà Nội", "Ha Noi" and "Hanoi" as three different places and splits the count
#: three ways — the same failure mode as raw skill tags, in a different field.
_CITY_ALIASES = {
    "hanoi": "Hà Nội",
    "ha noi": "Hà Nội",
    "hn": "Hà Nội",
    "ho chi minh": "Hồ Chí Minh",
    "ho chi minh city": "Hồ Chí Minh",
    "hochiminh": "Hồ Chí Minh",
    "saigon": "Hồ Chí Minh",
    "sai gon": "Hồ Chí Minh",
    "hcm": "Hồ Chí Minh",
    "hcmc": "Hồ Chí Minh",
    "tphcm": "Hồ Chí Minh",
    "danang": "Đà Nẵng",
    "da nang": "Đà Nẵng",
    "hue": "Huế",
    "can tho": "Cần Thơ",
    "hai phong": "Hải Phòng",
    "haiphong": "Hải Phòng",
}


def _fold_city(text: str) -> str:
    """``"Hà Nội"`` → ``"ha noi"`` — accents stripped, punctuation dropped.

    The same ASCII fold ``apply/inbox.fold`` uses, and for the same reason:
    Vietnamese place names are written with and without diacritics
    interchangeably, so comparison has to happen with them removed. ``đ`` has no
    combining form, so NFD leaves it alone and it is replaced by hand.
    """
    import unicodedata

    decomposed = unicodedata.normalize("NFD", (text or "").lower())
    folded = "".join(c for c in decomposed if not unicodedata.combining(c)).replace("đ", "d")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]+", " ", folded)).strip()


def canonical_city(text: str | None) -> str | None:
    """One agreed label for a city, whatever spelling the board used."""
    cleaned = clean_city(text)
    if not cleaned:
        return None
    folded = _fold_city(cleaned)
    if folded in _CITY_ALIASES:
        return _CITY_ALIASES[folded]
    # A known city written in full, accents and all: return the canonical
    # spelling from CITIES rather than whatever casing the board used.
    for city in CITIES:
        if _fold_city(city) == folded:
            return city
    return cleaned
