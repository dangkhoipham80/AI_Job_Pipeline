"""Phase 5: the tailor round — state machine, versioning, edit loop, failures."""

from __future__ import annotations

import pytest

from jobpilot.cv import store as cv_store
from jobpilot.store.models import Edit, Job, JobStatus, Run
from jobpilot.tailor import service
from jobpilot.tailor.build import BuildError
from jobpilot.tailor.engine import FixtureEngine, TailorError
from jobpilot.tailor.schema import Change, Requirement, SectionPlan, TailorPlan


@pytest.fixture
def db(session_factory):
    with session_factory() as s:
        cv_store.ensure_master(s)
        s.add(
            Job(
                id="itviec:1",
                source="itviec",
                title="Backend Engineer (Java)",
                company="ACME",
                status=JobStatus.SHORTLISTED,
                payload={"description_md": "Java, Spring Boot, Kafka", "skills": ["Java"]},
            )
        )
        s.commit()
        yield s


PLAN = TailorPlan(
    match_score=0.75,
    requirements=[
        Requirement(text="Java", kind="must_have", status="HAVE", evidence="experience: FPT"),
        Requirement(text="Kafka", kind="nice_to_have", status="MISSING"),
    ],
    summary="Backend engineer building **RESTful APIs** with `Spring Boot`.",
    sections=[SectionPlan(key="honors", enabled=False)],
    changes=[Change(section="summary", what="rewritten for backend", reason="must_have Java")],
)


def _engine(plan: TailorPlan = PLAN) -> FixtureEngine:
    return FixtureEngine(plan=plan)


def test_tailor_moves_job_to_review_and_saves_an_agent_version(db):
    outcome = service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)

    assert outcome.version == 1
    assert db.get(Job, "itviec:1").status == JobStatus.REVIEW
    row = cv_store.latest_version(db, "itviec:1")
    assert row.author == "agent"
    assert row.meta["match_score"] == 0.75
    assert row.meta["plan"]["summary"].startswith("Backend engineer")


def test_tailored_document_is_the_plan_applied_to_master(db):
    service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)
    doc = cv_store.get_document(db, "itviec:1")
    assert next(s for s in doc.sections if s.key == "honors").enabled is False
    assert next(s for s in doc.sections if s.key == "summary").text.startswith("Backend engineer")


def test_master_cv_is_untouched(db):
    """CLAUDE.md rule 3: tailoring must never write back to the Master."""
    before = cv_store.get_document(db, "master").model_dump()
    service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)
    assert cv_store.get_document(db, "master").model_dump() == before
    assert cv_store.latest_version(db, "master").version == 1


def test_match_score_lands_on_the_job_row(db):
    service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)
    assert db.get(Job, "itviec:1").match_score == 0.75


def test_gaps_are_recorded_not_hidden(db):
    outcome = service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)
    assert [g.text for g in outcome.plan.gaps()] == ["Kafka"]
    assert cv_store.latest_version(db, "itviec:1").meta["gaps"][0]["text"] == "Kafka"


def test_tailor_records_a_run(db):
    service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)
    run = db.query(Run).filter(Run.kind == "tailor").one()
    assert run.finished_at is not None
    assert run.stats["ok"] is True and run.stats["match_score"] == 0.75


def test_rerunning_appends_a_version(db):
    service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)
    second = service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)
    assert second.version == 2
    assert len(cv_store.list_versions(db, "itviec:1")) == 2


def test_tailor_refused_from_a_wrong_status(db):
    db.get(Job, "itviec:1").status = JobStatus.SUBMITTED
    db.commit()
    with pytest.raises(service.TailorRefused):
        service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)


def test_tailor_refused_for_unknown_job(db):
    with pytest.raises(service.TailorRefused):
        service.tailor_job(db, "nope:1", _engine(), compile_pdf=False)


# --------------------------------------------------------------------------- #
# Edit loop
# --------------------------------------------------------------------------- #
def test_edit_round_logs_the_instruction_and_passes_the_previous_plan(db):
    service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)
    engine = _engine()
    outcome = service.tailor_job(
        db, "itviec:1", engine, instruction="shorten it", compile_pdf=False
    )

    assert outcome.round == 1
    assert engine.calls == [("itviec:1", "shorten it")]
    assert db.query(Edit).one().instruction == "shorten it"


def test_edit_rounds_are_capped(db):
    from jobpilot.config import get_config

    limit = get_config().app.edit_max_rounds
    service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)
    for _ in range(limit):
        service.tailor_job(db, "itviec:1", _engine(), instruction="again", compile_pdf=False)
    with pytest.raises(service.TailorRefused, match="edit limit"):
        service.tailor_job(db, "itviec:1", _engine(), instruction="again", compile_pdf=False)


def test_latest_plan_is_the_base_for_an_edit(db):
    service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)
    assert service.latest_plan(db, "itviec:1").match_score == 0.75


# --------------------------------------------------------------------------- #
# Failures
# --------------------------------------------------------------------------- #
class _Boom:
    def __init__(self, exc):
        self.exc = exc

    def tailor(self, master, job, instruction=None, previous=None):
        raise self.exc


def test_engine_failure_marks_the_job_failed(db):
    with pytest.raises(TailorError):
        service.tailor_job(db, "itviec:1", _Boom(TailorError("api down")), compile_pdf=False)
    assert db.get(Job, "itviec:1").status == JobStatus.FAILED
    assert db.query(Run).one().stats["ok"] is False


def test_a_failed_job_can_be_retried(db):
    with pytest.raises(TailorError):
        service.tailor_job(db, "itviec:1", _Boom(TailorError("api down")), compile_pdf=False)
    outcome = service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)
    assert outcome.version == 1
    assert db.get(Job, "itviec:1").status == JobStatus.REVIEW


def test_build_failure_marks_the_job_failed(db, monkeypatch):
    def boom(doc, scope):
        raise BuildError("! Undefined control sequence")

    monkeypatch.setattr("jobpilot.tailor.service.compile_document", boom)
    with pytest.raises(BuildError):
        service.tailor_job(db, "itviec:1", _engine(), compile_pdf=True)
    assert db.get(Job, "itviec:1").status == JobStatus.FAILED
    # No half-written version left behind for a CV that never built.
    assert cv_store.list_versions(db, "itviec:1") == []


def test_page_count_is_recorded(db, monkeypatch):
    monkeypatch.setattr(
        "jobpilot.tailor.service.compile_document", lambda doc, scope: type("R", (), {"pages": 1})()
    )
    outcome = service.tailor_job(db, "itviec:1", _engine(), compile_pdf=True)
    assert outcome.pages == 1
    assert cv_store.latest_version(db, "itviec:1").meta["pages"] == 1


# --------------------------------------------------------------------------- #
# Approve / reject
# --------------------------------------------------------------------------- #
def test_approve_from_review(db):
    service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)
    assert service.approve(db, "itviec:1").status == JobStatus.APPROVED


def test_approve_requires_review(db):
    with pytest.raises(service.TailorRefused):
        service.approve(db, "itviec:1")


def test_reject_from_review(db):
    service.tailor_job(db, "itviec:1", _engine(), compile_pdf=False)
    assert service.reject(db, "itviec:1").status == JobStatus.SKIPPED
    # The tailored version survives the rejection as a record.
    assert len(cv_store.list_versions(db, "itviec:1")) == 1


def test_review_payload_before_any_tailoring(db):
    payload = service.review_payload(db, "itviec:1")
    assert payload["version"] == 0 and payload["meta"] == {}
