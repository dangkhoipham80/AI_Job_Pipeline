"""Phase 6: the apply endpoints and the Applications board."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobpilot.api.deps import get_db
from jobpilot.api.main import app
from jobpilot.api.routes.apply import get_letter_engine
from jobpilot.config import ApplyCfg, EmailCfg, get_secrets
from jobpilot.cv import store as cv_store
from jobpilot.cv.compile import scope_slug
from jobpilot.store.models import Job, JobStatus

AUTH = {"X-API-Token": get_secrets().jobpilot_api_token}


@pytest.fixture
def apply_cfg():
    """Mutable config the tests tweak per case (gates default to safe)."""
    return ApplyCfg(email=EmailCfg(enabled=True, from_addr="me@example.com", dry_run=True))


@pytest.fixture
def client(session_factory, tmp_path, monkeypatch, apply_cfg):
    monkeypatch.setattr(
        "jobpilot.apply.dispatcher.build_dir", lambda scope: tmp_path / scope_slug(scope)
    )
    # Both the dispatcher and the /settings route read config; patch both so the
    # board never reports gates that differ from the ones actually enforced.
    fake_config = lambda: type("C", (), {"apply": apply_cfg})()  # noqa: E731
    monkeypatch.setattr("jobpilot.apply.dispatcher.get_config", fake_config)
    monkeypatch.setattr("jobpilot.api.routes.apply.get_config", fake_config)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    with session_factory() as s:
        cv_store.ensure_master(s)
        s.add_all(
            [
                Job(
                    id="itviec:1",
                    source="itviec",
                    title="Backend Engineer",
                    company="ACME Corp",
                    status=JobStatus.APPROVED,
                    apply_channel="email",
                    apply_target="hr@acme.com",
                    payload={},
                ),
                Job(
                    id="itviec:2",
                    source="itviec",
                    title="Java Dev",
                    company="BetaCo",
                    status=JobStatus.APPROVED,
                    apply_channel="portal",
                    apply_target="https://beta.co/apply",
                    payload={},
                ),
            ]
        )
        s.commit()

    for job_id in ("itviec:1", "itviec:2"):
        pdf = tmp_path / scope_slug(job_id) / "cv.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF-1.4\n")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_letter_engine] = lambda: None
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def test_apply_requires_token(client):
    assert client.post("/jobs/itviec:1/apply").status_code == 401


def test_apply_route_is_not_shadowed_by_the_job_detail_route(client):
    r = client.post("/jobs/itviec:1/apply", headers=AUTH)
    assert r.status_code == 200 and r.json()["job_id"] == "itviec:1"


def test_dry_run_reports_that_nothing_was_sent(client):
    body = client.post("/jobs/itviec:1/apply", headers=AUTH).json()
    assert body["result"] == "dry_run"
    assert body["email"]["dry_run"] is True
    assert client.get("/jobs/itviec:1", headers=AUTH).json()["status"] == "APPROVED"


def test_test_recipient_is_reported_in_the_response(client, apply_cfg):
    apply_cfg.email.test_recipient = "me@example.com"
    body = client.post("/jobs/itviec:1/apply", headers=AUTH).json()
    assert body["email"]["to"] == "me@example.com"
    assert body["email"]["intended_to"] == "hr@acme.com"
    assert body["email"]["redirected"] is True


def test_portal_apply_returns_a_handoff_and_waits(client):
    body = client.post("/jobs/itviec:2/apply", headers=AUTH).json()
    assert body["result"] == "awaiting_user"
    assert body["handoff"]["url"] == "https://beta.co/apply"
    assert body["handoff"]["fields"]["email"]
    assert client.get("/jobs/itviec:2", headers=AUTH).json()["status"] == "SUBMITTING"


def test_confirm_submit_completes_the_application(client):
    client.post("/jobs/itviec:2/apply", headers=AUTH)
    r = client.post("/jobs/itviec:2/confirm-submit", headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "SUBMITTED"


def test_confirm_submit_conflicts_when_not_submitting(client):
    assert client.post("/jobs/itviec:1/confirm-submit", headers=AUTH).status_code == 409


def test_report_failure_records_the_reason(client):
    client.post("/jobs/itviec:2/apply", headers=AUTH)
    r = client.post(
        "/jobs/itviec:2/report-failure", headers=AUTH, json={"reason": "form rejected the CV"}
    )
    assert r.status_code == 200 and r.json()["status"] == "FAILED"
    row = next(
        a for a in client.get("/applications", headers=AUTH).json() if a["job_id"] == "itviec:2"
    )
    assert row["error_msg"] == "form rejected the CV"


def test_apply_404_for_unknown_job(client):
    assert client.post("/jobs/nope:1/apply", headers=AUTH).status_code == 404


def test_apply_409_from_a_wrong_status(client):
    client.post("/jobs/itviec:2/apply", headers=AUTH)
    client.post("/jobs/itviec:2/confirm-submit", headers=AUTH)
    assert client.post("/jobs/itviec:2/apply", headers=AUTH).status_code == 409


def test_board_lists_applications_with_job_context(client):
    client.post("/jobs/itviec:1/apply", headers=AUTH)
    client.post("/jobs/itviec:2/apply", headers=AUTH)
    rows = client.get("/applications", headers=AUTH).json()
    assert {r["job_id"] for r in rows} == {"itviec:1", "itviec:2"}
    first = next(r for r in rows if r["job_id"] == "itviec:1")
    assert first["company"] == "ACME Corp" and first["channel"] == "email"
    assert first["result"] == "dry_run"


def test_board_filters_by_result(client):
    client.post("/jobs/itviec:1/apply", headers=AUTH)
    client.post("/jobs/itviec:2/apply", headers=AUTH)
    rows = client.get("/applications?result=awaiting_user", headers=AUTH).json()
    assert [r["job_id"] for r in rows] == ["itviec:2"]


def test_settings_expose_the_gates(client, apply_cfg):
    apply_cfg.email.test_recipient = "me@example.com"
    body = client.get("/applications/settings", headers=AUTH).json()
    assert body["email_enabled"] is True
    assert body["email_dry_run"] is True
    assert body["email_test_recipient"] == "me@example.com"


def test_settings_report_why_email_is_blocked(client, apply_cfg, monkeypatch):
    monkeypatch.setattr(
        "jobpilot.api.routes.apply.get_config", lambda: type("C", (), {"apply": ApplyCfg()})()
    )
    assert "disabled" in client.get("/applications/settings", headers=AUTH).json()["email_blocker"]
