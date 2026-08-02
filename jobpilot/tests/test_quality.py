"""Job quality signals: why the score, and is the posting worth answering.

Nothing here filters a job out. These are annotations a person argues with, so
each one has to be defensible on its own — a flag you can't explain is a flag
you can't disagree with.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from jobpilot.crawler.normalize import VN_TZ, normalize
from jobpilot.crawler.quality import THIN_JD_CHARS, describe, flags_for, stack_coverage
from jobpilot.crawler.types import RawJob
from jobpilot.config import ApplyCfg, Config, CrawlCfg, CvCfg

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=VN_TZ)
STACKS = ["Java", "Spring Boot", "Kafka"]


# --------------------------------------------------------------------------- #
# explaining the score
# --------------------------------------------------------------------------- #
def test_coverage_names_both_sides_of_the_score():
    matched, missing = stack_coverage("Java and Spring Boot role", STACKS)
    assert matched == ["Java", "Spring Boot"]
    assert missing == ["Kafka"]


def test_the_explanation_agrees_with_the_number_it_explains():
    """If these two used different rules, the explanation would be a second,
    competing score — and the one shown to the user would be the wrong one."""
    from jobpilot.crawler.normalize import stack_match_score

    hay = "Senior Java engineer, some Kafka exposure"
    matched, missing = stack_coverage(hay, STACKS)
    assert round(len(matched) / len(STACKS), 3) == stack_match_score(hay, STACKS)
    assert len(matched) + len(missing) == len(STACKS)  # nothing falls between them


def test_coverage_is_case_insensitive_and_survives_an_empty_stack_list():
    assert stack_coverage("JAVA developer", ["java"])[0] == ["java"]
    assert stack_coverage("anything", []) == ([], [])


# --------------------------------------------------------------------------- #
# is the posting real
# --------------------------------------------------------------------------- #
def test_a_healthy_recent_posting_gets_no_flags():
    assert flags_for(description_md="x" * 2000, posted_at=NOW - timedelta(days=2), now=NOW) == []


def test_an_old_posting_is_flagged_stale():
    flags = flags_for(description_md="x" * 2000, posted_at=NOW - timedelta(days=90), now=NOW)
    assert flags == ["stale"]


def test_stale_respects_the_configured_window():
    old = NOW - timedelta(days=50)
    assert "stale" in flags_for(description_md="x" * 900, posted_at=old, now=NOW, stale_days=45)
    assert "stale" not in flags_for(description_md="x" * 900, posted_at=old, now=NOW, stale_days=60)


def test_unknown_age_is_not_old_age():
    """A source that publishes no date must not have its jobs quietly aged out —
    "undated" and "stale" are different claims, the way pages=None and pages=0
    are."""
    flags = flags_for(description_md="x" * 2000, posted_at=None, now=NOW)
    assert flags == ["undated"]
    assert "stale" not in flags


def test_a_headline_with_no_body_is_flagged_thin():
    flags = flags_for(description_md="Backend dev wanted", posted_at=NOW, now=NOW)
    assert "thin_jd" in flags


def test_thin_jd_boundary():
    assert "thin_jd" not in flags_for(description_md="x" * THIN_JD_CHARS, posted_at=NOW, now=NOW)
    assert "thin_jd" in flags_for(description_md="x" * (THIN_JD_CHARS - 1), posted_at=NOW, now=NOW)


def test_no_jd_supersedes_thin_jd():
    """A LinkedIn alert has no description by design. Reporting it as both
    missing and short is one fact stated twice."""
    flags = flags_for(description_md="", posted_at=NOW, needs_jd=True, now=NOW)
    assert flags == ["no_jd"]


def test_every_flag_has_something_a_person_can_do_about_it():
    for flag in ("no_jd", "thin_jd", "stale", "undated"):
        assert describe(flag) != flag
        assert len(describe(flag)) > 20


# --------------------------------------------------------------------------- #
# the whole thing, through normalize
# --------------------------------------------------------------------------- #
def _cfg(**kw) -> Config:
    return Config(crawl=CrawlCfg(stacks=STACKS, **kw), apply=ApplyCfg(), cv=CvCfg())


def test_normalize_attaches_the_explanation_to_the_payload():
    raw = RawJob(
        source="topcv",
        native_id="1",
        url="https://x/1",
        title="Java Backend Engineer",
        company="ACME",
        posted_raw="2026-08-01",
        description_md="We use Java and Spring Boot for our services. " * 20,
    )
    nj = normalize(raw, _cfg(), NOW)
    quality = nj.payload["quality"]
    assert quality["matched"] == ["Java", "Spring Boot"]
    assert quality["missing"] == ["Kafka"]
    assert quality["flags"] == []
    # The explanation must add up to the score that sits beside it.
    assert nj.match_score == round(len(quality["matched"]) / len(STACKS), 3)


def test_normalize_flags_an_old_thin_posting():
    raw = RawJob(
        source="topcv",
        native_id="2",
        url="https://x/2",
        title="Java dev",
        company="ACME",
        posted_raw="2026-01-01",
        description_md="Hiring now.",
    )
    quality = normalize(raw, _cfg(), NOW).payload["quality"]
    assert set(quality["flags"]) == {"thin_jd", "stale"}


# --------------------------------------------------------------------------- #
# jobs crawled before any of this existed
# --------------------------------------------------------------------------- #
def test_backfill_annotates_old_rows_and_is_idempotent(session_factory):
    """The jobs that need the flags most are the ones that will never be
    re-crawled — LinkedIn alerts carry no description at all."""
    from jobpilot.crawler.quality import backfill
    from jobpilot.store.models import Job, JobStatus

    with session_factory() as db:
        db.add(
            Job(
                id="linkedin:1",
                source="linkedin",
                url="u",
                title="Java Backend Developer",
                company="ACME",
                status=JobStatus.DISCOVERED,
                match_score=0.0,
                payload={"title": "Java Backend Developer", "description_md": "", "needs_jd": True},
            )
        )
        db.commit()

        assert backfill(db, _cfg(), now=NOW) == 1
        job = db.get(Job, "linkedin:1")
        # An alert email carries neither a description nor a date, and both are
        # worth saying: one blocks tailoring, the other blocks the 🔥 flag.
        assert job.payload["quality"]["flags"] == ["no_jd", "undated"]
        assert job.payload["quality"]["matched"] == ["Java"]

        # Running it twice must cost nothing and change nothing.
        assert backfill(db, _cfg(), now=NOW) == 0


def test_the_orm_row_exposes_quality_so_both_routes_get_it(session_factory):
    """FastAPI serializes ORM rows straight through `from_attributes`, so this
    property is the single place the list and the detail response both read."""
    from jobpilot.store.models import Job, JobStatus

    job = Job(
        id="x:1",
        source="x",
        url="u",
        title="t",
        company="c",
        status=JobStatus.DISCOVERED,
        match_score=0.0,
        payload={"quality": {"matched": ["Java"], "missing": [], "flags": ["stale"]}},
    )
    assert job.quality == {"matched": ["Java"], "missing": [], "flags": ["stale"]}
    assert Job(id="y", source="s", url="u", title="t", company="c", payload={}).quality is None
