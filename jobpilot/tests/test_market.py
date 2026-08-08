"""The derived facets, and the honesty attached to them.

Two kinds of test here. The first kind pins parsing — a salary label becoming
numbers, a board tag becoming a countable skill. The second kind pins the thing
that makes the Market page trustworthy: **every aggregate reports how much of
the corpus it saw**. A ranking without its denominator describes the boards that
tag their ads while looking like it describes the market, and this database is
57% LinkedIn, which tags nothing.
"""

from __future__ import annotations

from jobpilot.analytics import market
from jobpilot.crawler.salary import parse as parse_salary
from jobpilot.crawler.skills import canonicalise
from jobpilot.crawler.vietnam import canonical_city


# --------------------------------------------------------------------------- #
# salary
# --------------------------------------------------------------------------- #
def test_a_salary_label_becomes_numbers():
    vnd = parse_salary("20 - 60 triệu")
    assert (vnd.min, vnd.max, vnd.currency, vnd.period) == (20e6, 60e6, "VND", "month")

    usd = parse_salary("1,500 - 2,500 USD")
    assert (usd.min, usd.max, usd.currency) == (1500, 2500, "USD")

    yearly = parse_salary("120,000 - 160,000 USD/year")
    assert yearly.period == "year"
    # A yearly figure has to come down to a monthly one before it shares an axis
    # with a monthly one, or US remote roles dwarf every Vietnamese ad by 12x.
    assert yearly.usd_month == round(140_000 / 12, 2)


def test_the_unit_between_a_range_and_its_dash_is_not_lost():
    """"15tr - 25tr" parsed as 15–15: the unit broke the range pattern, so it
    fell through to the single-number branch and reported the floor as both
    bounds. A silently halved ceiling is the kind of wrong that looks right."""
    both = parse_salary("15tr - 25tr")
    assert (both.min, both.max) == (15e6, 25e6)


def test_a_salary_with_no_currency_is_refused():
    """"20 - 60" is millions of dong or dollars an hour depending on the board.
    Guessing would render a coin flip as a fact."""
    assert parse_salary("20 - 60") is None
    assert parse_salary("Thoả thuận") is None
    assert parse_salary("Negotiable") is None


def test_the_itviec_banner_is_not_a_salary():
    """A real row in the live database: the "IT Salary Report 2024-2025" banner
    was captured into the salary field by an older scraper. It must not become
    a number now that salaries are plotted."""
    assert parse_salary("IT Salary Report 2024-2025") is None


def test_up_to_has_no_floor_and_does_not_invent_one():
    capped = parse_salary("Up to 3,000 USD")
    assert capped.min is None and capped.max == 3000
    # Not 1500 — a midpoint against an imagined zero floor would drag the median
    # of the whole corpus down.
    assert capped.usd_month == 3000


# --------------------------------------------------------------------------- #
# skills
# --------------------------------------------------------------------------- #
def test_board_tags_become_countable_skills():
    out = canonicalise(["Java", "Spring Boot", "ReactJS", "spring boot", "+2", "Vollzeit"])
    # "+2" is an ITviec card's overflow badge; "Vollzeit" is German for
    # "full-time". Neither is a technology, and both outranked real stacks.
    assert out == ["java", "spring", "react"]


def test_a_role_is_not_a_skill_but_a_discipline_is():
    """Boards put "Backend Developer" in the same tag strip as "Java". The
    singular noun is the role; the -ing form is a field of work."""
    assert canonicalise(["Backend Developer", "Software Engineer"]) == []
    assert canonicalise(["Data Engineering"]) == ["data engineering"]


def test_industries_and_places_are_not_skills():
    assert canonicalise(["IT Services and IT Consulting", "India", "Financial Services"]) == []


# --------------------------------------------------------------------------- #
# cities
# --------------------------------------------------------------------------- #
def test_one_city_written_five_ways_counts_once():
    """Live data had Hà Nội split across three spellings, each with its own bar,
    each a third of the real number."""
    assert {canonical_city(t) for t in ("Ha Noi", "Hà Nội", "Hanoi", "HN")} == {"Hà Nội"}
    assert {canonical_city(t) for t in ("Ho Chi Minh", "Ho Chi Minh City", "TPHCM")} == {
        "Hồ Chí Minh"
    }


# --------------------------------------------------------------------------- #
# the aggregates, and their denominators
# --------------------------------------------------------------------------- #
def _payloads() -> list[dict]:
    return [
        {
            "source": "itviec",
            "skills_canonical": ["java", "spring"],
            "salary_range": {"usd_month": 1200},
            "city": "Hà Nội",
            "level": "senior",
            "match_score": 0.5,
            "posted_at": "2026-08-01T00:00:00+07:00",
            "quality": {"flags": []},
        },
        {
            "source": "linkedin",  # the shape that carries almost nothing
            "skills_canonical": [],
            "salary_range": None,
            "city": None,
            "level": None,
            "match_score": 0.25,
            "posted_at": None,
            "quality": {"flags": ["no_jd", "undated"]},
        },
    ]


def test_every_facet_reports_what_it_could_not_see():
    """The load-bearing test. A skills chart built from one of two jobs is a
    fact about one job; only the denominator says so."""
    payloads = _payloads()

    skills = market.top_skills(payloads)
    assert skills.covered == 1 and skills.total == 2
    assert skills.coverage == 0.5

    salary = market.salary_bands(payloads)
    assert salary.covered == 1
    assert "too few" in salary.note  # below MIN_SAMPLE

    # Every job is scored and every job lands in a quality bucket, so these two
    # are the only facets that legitimately claim full coverage.
    assert market.match_score_histogram(payloads).coverage == 1.0
    assert market.quality_flags(payloads).coverage == 1.0


def test_a_facet_with_nothing_in_it_says_so_rather_than_drawing_zero():
    bare = [{"source": "linkedin", "match_score": 0.1, "quality": {"flags": []}}]
    salary = market.salary_bands(bare)
    assert salary.covered == 0
    assert "No job" in salary.note
    # No summary row is appended when there is nothing to summarise — the page
    # would otherwise print a median of nothing.
    assert not any(r["key"] == "_summary" for r in salary.rows)


def test_remote_is_a_place_of_its_own():
    payloads = [
        {"is_remote": True, "city": None},
        {"is_remote": False, "city": "Hà Nội"},
    ]
    rows = {r["key"]: r["count"] for r in market.by_city(payloads).rows}
    assert rows == {"Remote": 1, "Hà Nội": 1}


def test_the_calendar_counts_posting_days_not_crawl_days():
    """The deck already charts `crawled_at`, which measures how often you ran
    the crawler. This has to measure the market instead."""
    payloads = [
        {"posted_at": "2026-08-01T09:00:00+07:00"},
        {"posted_at": "2026-08-01T18:00:00+07:00"},
        {"posted_at": "2026-08-02T09:00:00+07:00"},
        {"posted_at": None},
    ]
    facet = market.posting_calendar(payloads)
    assert {r["key"]: r["count"] for r in facet.rows} == {"2026-08-01": 2, "2026-08-02": 1}
    assert facet.covered == 3 and facet.total == 4


def test_microservices_survives_the_industry_filter():
    """The bug the review gate caught, and the reason it caught it and 658 tests
    did not: "services" with no word boundary is a substring of "microservices",
    so one of the most common tags on the market was dropped from every ranking.
    The chart still rendered perfectly — it was just missing an entry nobody
    could see was missing.

    Same shape as `"remote" in "remote debugging"` and `intern` inside
    `internal`, both of which this repo has already paid for once.
    """
    from jobpilot.crawler.skills import canonical

    assert canonical("microservices") == "microservices"
    assert canonical("web services") == "web services"
    # And the industry sense is still filtered, which is what the pattern is for.
    assert canonical("IT Services and IT Consulting") is None
    assert canonical("Financial Services") is None


def test_a_city_abbreviation_survives_the_production_path():
    """`canonical_city("TPHCM")` always answered correctly, but `derived_facets`
    gates on `looks_like_city`, which knew a different vocabulary — so the
    pipeline dropped it and the unit test passed anyway by calling the
    canonicaliser directly. Test the path production actually takes.
    """
    from jobpilot.crawler.normalize import derived_facets

    for spelling in ("HN", "TPHCM", "Saigon", "Ha Noi", "Hà Nội"):
        assert derived_facets(None, [], spelling)["city"] in {"Hà Nội", "Hồ Chí Minh"}

    # And a non-place still yields no city rather than a bogus one.
    assert derived_facets(None, [], "Anywhere in the World")["city"] is None
