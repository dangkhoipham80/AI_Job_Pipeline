"""Phase 2: FastAPI endpoint tests (TestClient over the SQLite fixture DB)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobpilot.api.deps import get_db
from jobpilot.api.main import app
from jobpilot.config import get_secrets
from jobpilot.store.models import Job, JobStatus

TOKEN = get_secrets().jobpilot_api_token


@pytest.fixture
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Seed a couple of jobs.
    with session_factory() as s:
        s.add_all(
            [
                Job(id="itviec:1", source="itviec", title="Backend", company="ACME"),
                Job(
                    id="topcv:2",
                    source="topcv",
                    title="Java Dev",
                    company="Foo",
                    status=JobStatus.SHORTLISTED,
                ),
            ]
        )
        s.commit()

    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _auth(c: TestClient) -> dict:
    return {"X-API-Token": TOKEN}


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_jobs_requires_token(client):
    assert client.get("/jobs").status_code == 401
    assert client.get("/stats").status_code == 401


def test_list_jobs(client):
    r = client.get("/jobs", headers=_auth(client))
    assert r.status_code == 200
    ids = {j["id"] for j in r.json()}
    assert ids == {"itviec:1", "topcv:2"}


def test_filter_jobs_by_source(client):
    r = client.get("/jobs", params={"source": "itviec"}, headers=_auth(client))
    assert [j["id"] for j in r.json()] == ["itviec:1"]


def test_get_job_detail_and_404(client):
    ok = client.get("/jobs/topcv:2", headers=_auth(client))
    assert ok.status_code == 200
    assert ok.json()["status"] == "SHORTLISTED"
    assert client.get("/jobs/nope:0", headers=_auth(client)).status_code == 404


def test_stats_funnel(client):
    r = client.get("/stats", headers=_auth(client))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["by_status"]["DISCOVERED"] == 1
    assert body["by_status"]["SHORTLISTED"] == 1
    assert body["by_status"]["SUBMITTED"] == 0  # every stage seeded
    assert body["by_source"] == {"itviec": 1, "topcv": 1}


def test_websocket_echo(client):
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        ws.send_text("ping")
        echo = ws.receive_json()
        assert echo == {"type": "echo", "data": "ping"}


def test_websocket_rejects_bad_token(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?token=wrong") as ws:
            ws.receive_json()
