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
    body = r.json()
    assert {j["id"] for j in body["items"]} == {"itviec:1", "topcv:2"}
    # The envelope reports the size of the whole result, not of the window.
    assert body["total"] == 2 and body["offset"] == 0


def test_filter_jobs_by_source(client):
    r = client.get("/jobs", params={"source": "itviec"}, headers=_auth(client))
    assert [j["id"] for j in r.json()["items"]] == ["itviec:1"]


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


def test_job_detail_includes_payload(client, session_factory):
    with session_factory() as s:
        s.add(
            Job(
                id="itviec:9",
                source="itviec",
                title="BE",
                company="Z",
                payload={"skills": ["Java", "Kafka"], "description_md": "# JD", "is_fresh": True},
            )
        )
        s.commit()
    r = client.get("/jobs/itviec:9", headers=_auth(client))
    assert r.status_code == 200
    body = r.json()
    assert body["skills"] == ["Java", "Kafka"]
    assert body["description_md"] == "# JD"
    assert body["is_fresh"] is True


def test_search_jobs_by_title(client):
    r = client.get("/jobs", params={"q": "java"}, headers=_auth(client))
    assert [j["id"] for j in r.json()["items"]] == ["topcv:2"]  # "Java Dev" matches, not "Backend"


def test_stats_extra_fields(client):
    body = client.get("/stats", headers=_auth(client)).json()
    assert "by_level" in body and "by_day" in body and "fresh" in body
    assert body["by_level"]["unknown"] == 2  # seeded jobs have no level


def test_shortlist_transition_and_broadcast(client, monkeypatch):
    from jobpilot.api import ws

    sent: list[dict] = []

    async def fake_broadcast(msg):
        sent.append(msg)

    monkeypatch.setattr(ws.manager, "broadcast", fake_broadcast)

    r = client.post("/jobs/itviec:1/shortlist", headers=_auth(client))
    assert r.status_code == 200
    assert r.json()["status"] == "SHORTLISTED"
    assert sent == [{"type": "job_updated", "id": "itviec:1", "status": "SHORTLISTED"}]


def test_skip_then_conflict_when_past_early(client, session_factory):
    # Force a job past the early funnel → shortlist/skip should 409.
    with session_factory() as s:
        s.get(Job, "itviec:1").status = JobStatus.SUBMITTED
        s.commit()
    r = client.post("/jobs/itviec:1/skip", headers=_auth(client))
    assert r.status_code == 409


def test_shortlist_404(client):
    assert client.post("/jobs/nope:0/shortlist", headers=_auth(client)).status_code == 404


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


def test_filter_jobs_by_run_id(client, session_factory):
    """A crawl's jobs are reachable from the run that found them."""
    from jobpilot.store.models import Run

    with session_factory() as s:
        run = Run(kind="crawl", stats={})
        s.add(run)
        s.flush()
        s.add(Job(id="linkedin:9", source="linkedin", title="BE", company="Z", run_id=run.id))
        run_id = run.id
        s.commit()

    r = client.get("/jobs", params={"run_id": run_id}, headers=_auth(client))
    assert [j["id"] for j in r.json()["items"]] == ["linkedin:9"]
    assert r.json()["items"][0]["run_id"] == run_id
    # `total` is counted with the same filter, not over the table.
    assert r.json()["total"] == 1

    # The seeded jobs belong to no run, so they must not leak into the view.
    assert client.get("/jobs", params={"run_id": run_id + 999}, headers=_auth(client)).json()["items"] == []


def test_filter_jobs_by_crawled_after(client, session_factory):
    """The crawl-time window is a floor, not a fuzzy match."""
    from datetime import timedelta

    from jobpilot.timeutil import vn_now

    now = vn_now()
    with session_factory() as s:
        s.add(
            Job(
                id="itviec:old",
                source="itviec",
                title="Old",
                company="A",
                crawled_at=now - timedelta(days=10),
            )
        )
        s.add(Job(id="itviec:new", source="itviec", title="New", company="B", crawled_at=now))
        s.commit()

    cutoff = (now - timedelta(days=1)).isoformat()
    ids = {
        j["id"]
        for j in client.get("/jobs", params={"crawled_after": cutoff}, headers=_auth(client)).json()["items"]
    }
    assert "itviec:new" in ids
    assert "itviec:old" not in ids


def test_runs_report_their_job_count(client, session_factory):
    """job_count is counted from the jobs, not read out of the run's stats blob."""
    from jobpilot.store.models import Run

    with session_factory() as s:
        run = Run(kind="crawl", stats={"inserted": 99})  # a lying stats blob
        s.add(run)
        s.flush()
        s.add_all(
            [
                Job(id=f"linkedin:{i}", source="linkedin", title="X", company="Y", run_id=run.id)
                for i in range(3)
            ]
        )
        s.commit()

    runs = client.get("/runs", headers=_auth(client)).json()["items"]
    assert runs[0]["job_count"] == 3
