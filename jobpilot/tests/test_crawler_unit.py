"""Phase 3: pure-unit tests for crawler helpers (no DB, no network)."""

from __future__ import annotations

from datetime import datetime, timedelta

from jobpilot.crawler.normalize import (
    VN_TZ,
    infer_level,
    parse_posted_at,
    stack_match_score,
    title_excluded,
)
from jobpilot.crawler.ratelimit import RateLimiter
from jobpilot.crawler.robots import RobotsPolicy
from jobpilot.crawler.text import clean_text, dedup_key, html_to_markdown, normalize_title

NOW = datetime(2026, 7, 10, 12, 0, tzinfo=VN_TZ)


# -- text ------------------------------------------------------------------- #
def test_clean_text_collapses_whitespace_and_nbsp():
    assert clean_text("  a\xa0\n b   c ") == "a b c"


def test_html_to_markdown_keeps_headings_and_bullets():
    md = html_to_markdown("<h2>Reqs</h2><ul><li>Java</li><li>Spring</li></ul><p>Nice</p>")
    assert "## Reqs" in md
    assert "- Java" in md and "- Spring" in md
    assert "Nice" in md


def test_html_to_markdown_flat_fallback():
    assert html_to_markdown("just text") == "just text"


def test_normalize_title_drops_level_and_parens():
    assert normalize_title("Senior Java Backend (Spring Boot)") == "java backend"
    assert normalize_title("Junior Java Backend") == "java backend"


def test_dedup_key_is_case_and_level_insensitive():
    assert dedup_key("ACME Corp", "Senior Java Dev") == dedup_key("acme corp", "Java Dev")


# -- posted_at -------------------------------------------------------------- #
def test_parse_posted_at_relative_english():
    assert parse_posted_at("3 days ago", NOW) == NOW - timedelta(days=3)
    assert parse_posted_at("2 hours ago", NOW) == NOW - timedelta(hours=2)


def test_parse_posted_at_vietnamese():
    assert parse_posted_at("2 ngày trước", NOW) == NOW - timedelta(days=2)
    assert parse_posted_at("hôm qua", NOW) == NOW - timedelta(days=1)
    assert parse_posted_at("hôm nay", NOW) == NOW


def test_parse_posted_at_absolute_daymonth():
    dt = parse_posted_at("08/07/2026", NOW)
    assert dt == datetime(2026, 7, 8, tzinfo=VN_TZ)


def test_parse_posted_at_rfc822_from_rss():
    """Every RSS feed dates its items RFC-822, which ISO parsing rejects. Left
    unhandled, a feed source lands with posted_at=None — never flagged fresh,
    missing from the by-day chart — while looking perfectly healthy."""
    dt = parse_posted_at("Wed, 22 Jul 2026 07:00:51 +0000", NOW)
    assert dt is not None
    assert (dt.year, dt.month, dt.day, dt.hour) == (2026, 7, 22, 7)
    assert dt.utcoffset() == timedelta(0)


def test_parse_posted_at_unparseable_returns_none():
    assert parse_posted_at("", NOW) is None
    assert parse_posted_at("recently", NOW) is None
    # Still None, not a date invented out of a weekday name.
    assert parse_posted_at("Wednesday", NOW) is None


# -- level + matching ------------------------------------------------------- #
def test_infer_level_priority():
    assert infer_level("Fresher Java Developer") == "fresher"
    assert infer_level("Backend Intern") == "intern"
    assert infer_level("Senior Backend Engineer") == "senior"
    assert infer_level("Backend Engineer") is None


def test_infer_level_matches_words_not_substrings():
    """ "intern" hides inside "internal"/"international" and "lead" inside
    "leadership" — words nearly every JD uses. Substring matching filed a Stripe
    senior role as an internship, and that wrong level flows into the dashboard
    chart and the level filter looking perfectly plausible."""
    assert infer_level("Backend Engineer", "You work with internal teams") is None
    assert infer_level("Backend Engineer", "our international offices") is None
    assert infer_level("Backend Engineer", "strong leadership skills") is None
    # The real words still match, in the title or the body.
    assert infer_level("Backend Engineer", "This is an internship") == "intern"
    assert infer_level("Tech Lead") == "senior"
    assert infer_level("Thực tập sinh Java") == "intern"


def test_bare_intern_counts_in_the_title_but_not_in_prose():
    """ "intern" is an ordinary word in a JD — English "internally", German
    "beraten wir uns intern" (seen live on Arbeitnow) — but never an accident in
    a job title. "Internship" is unambiguous anywhere."""
    assert infer_level("Backend Intern") == "intern"
    assert infer_level("Software Engineer", "beraten wir uns intern") is None
    assert infer_level("Software Engineer", "we discuss it intern") is None
    assert infer_level("Software Engineer", "a paid internship") == "intern"


def test_stack_match_score_fraction():
    stacks = ["Java", "Spring Boot", "Kafka", "Docker"]
    assert stack_match_score("Java and Spring Boot role", stacks) == 0.5
    assert stack_match_score("Golang only", stacks) == 0.0
    assert stack_match_score("anything", []) == 0.0


def test_title_excluded_matches_title_only():
    kws = ["Senior", "Lead", ".NET"]
    assert title_excluded("Senior Java Dev", kws) is True
    assert title_excluded("Junior Java Dev", kws) is False


# -- rate limiter ----------------------------------------------------------- #
def test_rate_limiter_uses_injected_sleep_within_bounds():
    slept: list[float] = []
    rl = RateLimiter(1.0, 3.0, sleep=slept.append)
    d = rl.wait()
    assert 1.0 <= d <= 3.0
    assert slept == [d]


def test_rate_limiter_disabled_when_high_nonpositive():
    slept: list[float] = []
    rl = RateLimiter(0.0, 0.0, sleep=slept.append)
    assert rl.wait() == 0.0
    assert slept == []


# -- robots ----------------------------------------------------------------- #
def test_robots_disallow_and_allow():
    robots_txt = "User-agent: *\nDisallow: /private\n"
    policy = RobotsPolicy("bot", fetch=lambda url: robots_txt)
    assert policy.allowed("https://x.com/public/page") is True
    assert policy.allowed("https://x.com/private/page") is False


def test_robots_missing_file_allows():
    policy = RobotsPolicy("bot", fetch=lambda url: None, allow_on_error=True)
    assert policy.allowed("https://x.com/anything") is True


def test_normalize_clamps_fields_to_column_widths():
    """Postgres raises StringDataRightTruncation mid-flush on an overlong value
    and rolls back the entire crawl, so one runaway field would cost every job in
    the batch. Truncating keeps the damage to that field."""
    from jobpilot.config import ApplyCfg, Config, CrawlCfg, CvCfg
    from jobpilot.crawler.normalize import normalize
    from jobpilot.crawler.types import RawJob

    cfg = Config(crawl=CrawlCfg(stacks=[]), apply=ApplyCfg(), cv=CvCfg())
    raw = RawJob(
        source="topcv",
        native_id="1",
        url="https://x/1",
        title="T" * 900,
        company="C" * 900,
        location="L" * 900,
        salary="S" * 900,
    )
    nj = normalize(raw, cfg)
    assert len(nj.title) == 256
    assert len(nj.company) == 256
    assert len(nj.location) == 256
    assert len(nj.salary) == 128


def test_normalize_keeps_none_apart_from_empty_string():
    """`salary=None` means "not disclosed"; "" would read as a published blank."""
    from jobpilot.config import ApplyCfg, Config, CrawlCfg, CvCfg
    from jobpilot.crawler.normalize import normalize
    from jobpilot.crawler.types import RawJob

    cfg = Config(crawl=CrawlCfg(stacks=[]), apply=ApplyCfg(), cv=CvCfg())
    nj = normalize(RawJob(source="s", native_id="1", url="u", title="t"), cfg)
    assert nj.salary is None
    assert nj.location is None
