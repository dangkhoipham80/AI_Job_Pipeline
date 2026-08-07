"""Phase 5: the tailor/review API surface (fixture engine — no network, no Docker)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobpilot.api.deps import get_db
from jobpilot.api.main import app
from jobpilot.api.routes.review import get_engine
from jobpilot.config import get_secrets
from jobpilot.cv import store as cv_store
from jobpilot.store.models import Job, JobStatus
from jobpilot.tailor.engine import FixtureEngine
from jobpilot.tailor.schema import Change, Requirement, SectionPlan, TailorPlan

AUTH = {"X-API-Token": get_secrets().jobpilot_api_token}

PLAN = TailorPlan(
    match_score=0.8,
    requirements=[
        Requirement(text="Java", kind="must_have", status="HAVE", evidence="experience"),
        Requirement(text="Kafka", kind="nice_to_have", status="MISSING"),
    ],
    summary="Backend engineer with `Spring Boot` and **RESTful APIs**.",
    sections=[SectionPlan(key="honors", enabled=False)],
    changes=[Change(section="honors", what="hidden", reason="one-page budget")],
)


@pytest.fixture
def tailor_engine() -> FixtureEngine:
    return FixtureEngine(plan=PLAN)


@pytest.fixture
def client(session_factory, tailor_engine, monkeypatch):
    # Skip the Docker build; page count is exercised in the service tests.
    monkeypatch.setattr(
        "jobpilot.tailor.service.compile_document", lambda doc, scope: type("R", (), {"pages": 1})()
    )

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    with session_factory() as s:
        cv_store.ensure_master(s)
        s.add(
            Job(
                id="itviec:1",
                source="itviec",
                title="Backend Engineer",
                company="ACME",
                status=JobStatus.SHORTLISTED,
                payload={"description_md": "Java, Spring Boot", "skills": ["Java"]},
            )
        )
        s.commit()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_engine] = lambda: tailor_engine
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def test_tailor_requires_token(client):
    assert client.post("/jobs/itviec:1/tailor").status_code == 401


def test_tailor_answers_immediately_with_a_queued_task(client, run_task):
    """The point of the phase: the request returns before the work starts."""
    r = client.post("/jobs/itviec:1/tailor", headers=AUTH)
    assert r.status_code == 202
    body = r.json()
    assert body["kind"] == "tailor" and body["job_id"] == "itviec:1"
    assert body["status"] in ("queued", "running") and body["finished_at"] is None
    run_task(client, r)


def test_tailor_task_carries_the_headline_numbers(client, run_task):
    """Kept small on purpose: /tasks returns 50 of these at once, and the plan
    and diff already have a home in cv_versions, served by /review."""
    task = run_task(client, client.post("/jobs/itviec:1/tailor", headers=AUTH))
    assert task["status"] == "done", task["error"]
    assert task["result"]["version"] == 1
    assert task["result"]["match_score"] == 0.8 and task["result"]["pages"] == 1
    assert task["result"]["gaps"] == 1


def test_tailor_produces_the_plan_and_diff_on_the_review_endpoint(client, run_task):
    run_task(client, client.post("/jobs/itviec:1/tailor", headers=AUTH))
    body = client.get("/jobs/itviec:1/review", headers=AUTH).json()
    assert body["version"] == 1 and body["plan"]["summary"].startswith("Backend engineer")
    honors = next(s for s in body["diff"]["sections"] if s["key"] == "honors")
    assert honors["status"] == "hidden"


def test_a_second_task_for_the_same_job_is_refused(client, hold_task):
    """One at a time per job: two rounds would race the same build directory."""
    hold_task("itviec:1")
    r = client.post("/jobs/itviec:1/tailor", headers=AUTH)
    assert r.status_code == 409 and "already" in r.json()["detail"]


def test_a_task_for_another_job_does_not_block_this_one(client, run_task, hold_task):
    hold_task("itviec:2")
    assert client.post("/jobs/itviec:1/tailor", headers=AUTH).status_code == 202


def test_review_route_is_not_shadowed_by_the_job_detail_route(client, run_task):
    """/jobs/{id:path} is greedy — the review router must be matched first."""
    run_task(client, client.post("/jobs/itviec:1/tailor", headers=AUTH))
    r = client.get("/jobs/itviec:1/review", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["job_id"] == "itviec:1"


def test_review_before_tailoring_is_empty_but_valid(client):
    body = client.get("/jobs/itviec:1/review", headers=AUTH).json()
    assert body["version"] == 0 and body["plan"] is None and body["gaps"] == []


def test_review_exposes_gaps(client, run_task):
    run_task(client, client.post("/jobs/itviec:1/tailor", headers=AUTH))
    body = client.get("/jobs/itviec:1/review", headers=AUTH).json()
    assert [g["text"] for g in body["gaps"]] == ["Kafka"]
    assert body["match_score"] == 0.8


def test_review_404_for_unknown_job(client):
    assert client.get("/jobs/nope:1/review", headers=AUTH).status_code == 404


def test_tailor_conflict_from_a_wrong_status(client, run_task):
    """Still refused in the request, not by a task that fails a minute later."""
    run_task(client, client.post("/jobs/itviec:1/tailor", headers=AUTH))
    client.post("/jobs/itviec:1/approve", headers=AUTH)
    r = client.post("/jobs/itviec:1/tailor", headers=AUTH)
    assert r.status_code == 409


def test_edit_passes_the_instruction_to_the_engine(client, run_task, tailor_engine):
    run_task(client, client.post("/jobs/itviec:1/tailor", headers=AUTH))
    task = run_task(
        client,
        client.post("/jobs/itviec:1/edit", headers=AUTH, json={"instruction": "shorten summary"}),
    )
    assert task["status"] == "done" and task["result"]["version"] == 2
    assert task["result"]["round"] == 1
    assert tailor_engine.calls[-1] == ("itviec:1", "shorten summary")


def test_edit_rejects_an_empty_instruction(client, run_task):
    run_task(client, client.post("/jobs/itviec:1/tailor", headers=AUTH))
    r = client.post("/jobs/itviec:1/edit", headers=AUTH, json={"instruction": "   "})
    assert r.status_code == 422


def test_guardrail_violation_fails_the_task_and_writes_no_cv(client, run_task):
    """A plan that would invent a skill must never reach the CV.

    Off the request path this can no longer be a 422, so the task carries the
    alarm instead — which is what ``error_kind`` exists for: the UI keys on it
    to flag a truthfulness failure rather than a build hiccup.
    """
    bad = PLAN.model_copy(update={"summary": "Expert in Golang and Terraform."})
    app.dependency_overrides[get_engine] = lambda: FixtureEngine(plan=bad)
    task = run_task(client, client.post("/jobs/itviec:1/tailor", headers=AUTH))
    assert task["status"] == "failed"
    assert task["error_kind"] == "GuardrailViolation" and "Golang" in task["error"]
    assert client.get("/jobs/itviec:1/review", headers=AUTH).json()["version"] == 0
    assert client.get("/jobs/itviec:1", headers=AUTH).json()["status"] == "FAILED"


def test_an_unexpected_failure_does_not_strand_the_job_in_tailoring(client, run_task):
    """The service commits TAILORING before the slow part and only converts it to
    FAILED for the failures it expects. Anything else used to leave the job
    saying "working on it" with nothing working on it."""

    class Exploding:
        def tailor(self, master, job, instruction=None, previous=None):
            raise KeyError("summary")  # not a TailorError/GuardrailViolation/BuildError

    app.dependency_overrides[get_engine] = lambda: Exploding()
    task = run_task(client, client.post("/jobs/itviec:1/tailor", headers=AUTH))
    assert task["status"] == "failed" and task["error_kind"] == "KeyError"
    assert client.get("/jobs/itviec:1", headers=AUTH).json()["status"] == "FAILED"


def test_approve_moves_to_approved(client, run_task):
    run_task(client, client.post("/jobs/itviec:1/tailor", headers=AUTH))
    r = client.post("/jobs/itviec:1/approve", headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"


def test_approve_requires_review(client):
    assert client.post("/jobs/itviec:1/approve", headers=AUTH).status_code == 409


def test_reject_moves_to_skipped(client, run_task):
    run_task(client, client.post("/jobs/itviec:1/tailor", headers=AUTH))
    assert client.post("/jobs/itviec:1/reject", headers=AUTH).json()["status"] == "SKIPPED"


def test_tailored_pdf_404_before_build(client, run_task, monkeypatch, tmp_path):
    monkeypatch.setattr("jobpilot.api.routes.review.build_dir", lambda scope: tmp_path / "x")
    run_task(client, client.post("/jobs/itviec:1/tailor", headers=AUTH))
    assert client.get("/jobs/itviec:1/cv", headers=AUTH).status_code == 404


def test_tailored_pdf_served_after_build(client, monkeypatch, tmp_path):
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr("jobpilot.api.routes.review.build_dir", lambda scope: tmp_path)
    r = client.get("/jobs/itviec:1/cv", headers=AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"


def test_job_detail_still_works_alongside_the_review_routes(client):
    r = client.get("/jobs/itviec:1", headers=AUTH)
    assert r.status_code == 200 and r.json()["id"] == "itviec:1"
