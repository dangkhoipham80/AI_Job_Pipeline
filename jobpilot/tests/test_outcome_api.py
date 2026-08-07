"""Phase 18: recording outcomes over HTTP, and the numbers they feed.

Seeds applications directly rather than driving a dispatch: the gates make a
real send a dry run, and a dry run is precisely the thing that must *not* be
allowed to carry an outcome — so the fixture builds the states the board can
actually reach and pushes on the boundaries between them.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobpilot.api.deps import get_db
from jobpilot.api.main import app
from jobpilot.config import get_secrets
from jobpilot.store.models import Application, Job, JobStatus

AUTH = {"X-API-Token": get_secrets().jobpilot_api_token}


@pytest.fixture
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    with session_factory() as s:
        s.add_all(
            [
                Job(
                    id="itviec:1",
                    source="itviec",
                    title="Backend Engineer",
                    company="ACME Corp",
                    status=JobStatus.SUBMITTED,
                    payload={},
                ),
                Job(
                    id="itviec:2",
                    source="itviec",
                    title="Java Dev",
                    company="BetaCo",
                    status=JobStatus.APPROVED,
                    payload={},
                ),
            ]
        )
        s.flush()
        s.add_all(
            [
                # A real send, and a dry run that must stay out of every number.
                Application(job_id="itviec:1", channel="email", result="success"),
                Application(job_id="itviec:2", channel="email", result="dry_run"),
            ]
        )
        s.commit()

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _sent(client) -> int:
    return next(
        a["id"]
        for a in client.get("/applications", headers=AUTH).json()
        if a["result"] == "success"
    )


def _dry(client) -> int:
    return next(
        a["id"]
        for a in client.get("/applications", headers=AUTH).json()
        if a["result"] == "dry_run"
    )


def _outcomes(client) -> dict:
    return client.get("/stats", headers=AUTH).json()["outcomes"]


# --------------------------------------------------------------------------- #
# recording
# --------------------------------------------------------------------------- #
def test_recording_an_outcome_requires_a_token(client):
    assert client.post("/applications/1/outcome", json={"event_type": "replied"}).status_code == 401


def test_the_outcome_route_is_not_shadowed_by_the_board_routes(client):
    """``/applications/{id}/...`` shares a prefix with ``/applications`` and
    ``/applications/followups``; registration order decides whether it resolves."""
    r = client.post(
        f"/applications/{_sent(client)}/outcome", headers=AUTH, json={"event_type": "replied"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["outcome_stage"] == "replied"
    assert r.json()["outcome_hint"]


def test_recording_stops_the_follow_up_cadence(client):
    app_id = _sent(client)
    client.post(f"/applications/{app_id}/outcome", headers=AUTH, json={"event_type": "replied"})
    row = next(a for a in client.get("/applications", headers=AUTH).json() if a["id"] == app_id)
    assert row["next_followup_at"] is None
    assert row["followup_due"] is False


def test_an_unknown_application_is_a_404(client):
    r = client.post("/applications/9999/outcome", headers=AUTH, json={"event_type": "replied"})
    assert r.status_code == 404


def test_a_dry_run_is_refused_with_a_409(client):
    """Nothing left the machine, so nobody could have answered — and letting it
    through would corrupt the denominator every rate divides by."""
    r = client.post(
        f"/applications/{_dry(client)}/outcome", headers=AUTH, json={"event_type": "replied"}
    )
    assert r.status_code == 409
    assert "nobody" in r.json()["detail"]


def test_an_invalid_outcome_is_a_422(client):
    r = client.post(
        f"/applications/{_sent(client)}/outcome", headers=AUTH, json={"event_type": "maybe"}
    )
    assert r.status_code == 422


def test_the_label_survives_the_round_trip(client):
    app_id = _sent(client)
    client.post(
        f"/applications/{app_id}/outcome",
        headers=AUTH,
        json={
            "event_type": "interview",
            "label": "Round 1 — Technical",
            "notes": "60 min, system design",
        },
    )
    events = client.get(f"/applications/{app_id}/events", headers=AUTH).json()
    assert events[0]["label"] == "Round 1 — Technical"
    assert events[0]["notes"].startswith("60 min")


def test_an_over_long_label_never_reaches_the_column(client):
    """Postgres enforces VARCHAR(128) where SQLite shrugs, so an over-long label
    would otherwise only fail in production — and fail mid-flush, which is how a
    single bad field has taken out a whole batch in this codebase before.

    Two different answers by design. Over HTTP a human typed it, so a 422 saying
    so beats silently storing something other than what they wrote. Called
    directly — as Phase 19 will, with a mail subject line — ``record_outcome``
    clamps instead, because there is no human there to re-type it.
    """
    r = client.post(
        f"/applications/{_sent(client)}/outcome",
        headers=AUTH,
        json={"event_type": "interview", "label": "R" * 400},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# history and retraction
# --------------------------------------------------------------------------- #
def test_the_history_is_oldest_first(client):
    app_id = _sent(client)
    for event_type in ("replied", "interview", "rejected"):
        client.post(
            f"/applications/{app_id}/outcome", headers=AUTH, json={"event_type": event_type}
        )
    events = client.get(f"/applications/{app_id}/events", headers=AUTH).json()
    assert [e["event_type"] for e in events] == ["replied", "interview", "rejected"]


def test_history_of_an_unknown_application_is_a_404(client):
    """Not an empty list: "no history" and "no such application" are different
    answers, and the board renders them differently."""
    assert client.get("/applications/9999/events", headers=AUTH).status_code == 404


def test_retracting_rewinds_the_stage(client):
    app_id = _sent(client)
    client.post(f"/applications/{app_id}/outcome", headers=AUTH, json={"event_type": "replied"})
    client.post(f"/applications/{app_id}/outcome", headers=AUTH, json={"event_type": "interview"})
    events = client.get(f"/applications/{app_id}/events", headers=AUTH).json()

    r = client.delete(f"/applications/{app_id}/events/{events[-1]['id']}", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["outcome_stage"] == "replied"

    after = client.get(f"/applications/{app_id}/events", headers=AUTH).json()
    assert [e["is_retracted"] for e in after] == [False, True]


def test_retracting_an_event_of_another_application_is_a_404(client):
    app_id = _sent(client)
    client.post(f"/applications/{app_id}/outcome", headers=AUTH, json={"event_type": "offer"})
    event_id = client.get(f"/applications/{app_id}/events", headers=AUTH).json()[0]["id"]
    assert (
        client.delete(f"/applications/{_dry(client)}/events/{event_id}", headers=AUTH).status_code
        == 404
    )


# --------------------------------------------------------------------------- #
# stats
# --------------------------------------------------------------------------- #
def test_a_dry_run_is_in_no_denominator(client):
    out = _outcomes(client)
    assert out["total_real"] == 1  # the dry run is not one of them
    assert out["no_outcome"] == 1


def test_a_rate_with_nothing_to_divide_by_is_unknown_not_zero(client):
    """ "0% of nothing" is a claim about the world; None is the truth, and the
    dashboard renders it as a dash.

    Note the asymmetry this pins: ``reply_rate`` *is* 0.0 here, because one
    application really was sent and really hasn't answered. Only the empty
    denominator is unknowable — guarding a small-but-real sample is the UI's
    job (it refuses to show a percentage under ten), not arithmetic's.
    """
    out = _outcomes(client)
    assert out["reply_rate"] == 0.0
    assert out["reached"]["interview"] == 0
    assert out["offer_rate"] is None  # no interviews to divide by


def test_an_interview_still_counts_after_the_rejection(client):
    """The regression that makes the two count sets necessary: reading the rate
    off the board's current column would report the applications *stuck* in
    interviews rather than the ones that got one."""
    app_id = _sent(client)
    client.post(f"/applications/{app_id}/outcome", headers=AUTH, json={"event_type": "interview"})
    client.post(f"/applications/{app_id}/outcome", headers=AUTH, json={"event_type": "rejected"})

    out = _outcomes(client)
    assert out["current"]["rejected"] == 1
    assert out["current"]["interview"] == 0
    assert out["reached"]["interview"] == 1
    assert out["interview_rate"] == 1.0


def test_the_funnel_still_stops_at_submitted(client):
    """Outcomes live on the application, not on ``job_status`` — a job that was
    rejected is still a job that was SUBMITTED, and the enum is unchanged."""
    app_id = _sent(client)
    client.post(f"/applications/{app_id}/outcome", headers=AUTH, json={"event_type": "rejected"})
    by_status = client.get("/stats", headers=AUTH).json()["by_status"]
    assert by_status["SUBMITTED"] == 1
    assert "REJECTED" not in by_status
