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


def test_tailor_returns_plan_and_diff(client):
    r = client.post("/jobs/itviec:1/tailor", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1 and body["match_score"] == 0.8 and body["pages"] == 1
    assert body["plan"]["summary"].startswith("Backend engineer")
    honors = next(s for s in body["diff"]["sections"] if s["key"] == "honors")
    assert honors["status"] == "hidden"


def test_review_route_is_not_shadowed_by_the_job_detail_route(client):
    """/jobs/{id:path} is greedy — the review router must be matched first."""
    client.post("/jobs/itviec:1/tailor", headers=AUTH)
    r = client.get("/jobs/itviec:1/review", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["job_id"] == "itviec:1"


def test_review_before_tailoring_is_empty_but_valid(client):
    body = client.get("/jobs/itviec:1/review", headers=AUTH).json()
    assert body["version"] == 0 and body["plan"] is None and body["gaps"] == []


def test_review_exposes_gaps(client):
    client.post("/jobs/itviec:1/tailor", headers=AUTH)
    body = client.get("/jobs/itviec:1/review", headers=AUTH).json()
    assert [g["text"] for g in body["gaps"]] == ["Kafka"]
    assert body["match_score"] == 0.8


def test_review_404_for_unknown_job(client):
    assert client.get("/jobs/nope:1/review", headers=AUTH).status_code == 404


def test_tailor_conflict_from_a_wrong_status(client):
    client.post("/jobs/itviec:1/tailor", headers=AUTH)
    client.post("/jobs/itviec:1/approve", headers=AUTH)
    r = client.post("/jobs/itviec:1/tailor", headers=AUTH)
    assert r.status_code == 409


def test_edit_passes_the_instruction_to_the_engine(client, tailor_engine):
    client.post("/jobs/itviec:1/tailor", headers=AUTH)
    r = client.post("/jobs/itviec:1/edit", headers=AUTH, json={"instruction": "shorten summary"})
    assert r.status_code == 200 and r.json()["version"] == 2
    assert tailor_engine.calls[-1] == ("itviec:1", "shorten summary")


def test_edit_rejects_an_empty_instruction(client):
    client.post("/jobs/itviec:1/tailor", headers=AUTH)
    r = client.post("/jobs/itviec:1/edit", headers=AUTH, json={"instruction": "   "})
    assert r.status_code == 422


def test_guardrail_violation_surfaces_as_422(client):
    """A plan that would invent a skill must fail the request, not reach the CV."""
    bad = PLAN.model_copy(update={"summary": "Expert in Golang and Terraform."})
    app.dependency_overrides[get_engine] = lambda: FixtureEngine(plan=bad)
    r = client.post("/jobs/itviec:1/tailor", headers=AUTH)
    assert r.status_code == 422
    assert "Golang" in r.json()["detail"]


def test_approve_moves_to_approved(client):
    client.post("/jobs/itviec:1/tailor", headers=AUTH)
    r = client.post("/jobs/itviec:1/approve", headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"


def test_approve_requires_review(client):
    assert client.post("/jobs/itviec:1/approve", headers=AUTH).status_code == 409


def test_reject_moves_to_skipped(client):
    client.post("/jobs/itviec:1/tailor", headers=AUTH)
    assert client.post("/jobs/itviec:1/reject", headers=AUTH).json()["status"] == "SKIPPED"


def test_tailored_pdf_404_before_build(client, monkeypatch, tmp_path):
    monkeypatch.setattr("jobpilot.api.routes.review.build_dir", lambda scope: tmp_path / "x")
    client.post("/jobs/itviec:1/tailor", headers=AUTH)
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
