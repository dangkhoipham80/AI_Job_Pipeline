"""Phase 7: the Slack surface.

The client is pointed straight at the real ASGI app, so these exercise the same
endpoints and the same state machine the dashboard uses — which is the whole
claim of the design (PLAN.md §10: Web and Slack cannot diverge because they
share one code path).
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from jobpilot.api.deps import get_db
from jobpilot.api.main import app as fastapi_app
from jobpilot.api.routes.apply import get_letter_engine
from jobpilot.api.routes.review import get_engine
from jobpilot.config import ApplyCfg, EmailCfg, get_secrets
from jobpilot.cv import store as cv_store
from jobpilot.cv.compile import scope_slug
from jobpilot.slack import blocks as B
from jobpilot.slack.client import ApiError, JobPilotClient
from jobpilot.slack.events import digest, notification_for, outcome_from_application
from jobpilot.store.models import Job, JobStatus
from jobpilot.tailor.engine import FixtureEngine
from jobpilot.tailor.schema import Change, Requirement, SectionPlan, TailorPlan

PLAN = TailorPlan(
    match_score=0.8,
    requirements=[
        Requirement(text="Java", kind="must_have", status="HAVE", evidence="experience"),
        Requirement(text="Kafka", kind="nice_to_have", status="MISSING"),
    ],
    summary="Backend engineer with `Spring Boot` and **RESTful APIs**.",
    sections=[SectionPlan(key="honors", enabled=False)],
    changes=[Change(section="honors", what="Honors hidden", reason="one-page budget")],
)


def finish(client: JobPilotClient, task: dict, timeout: float = 20.0) -> dict:
    """Drive a 202 task to completion.

    Slack itself never waits — it acknowledges "queued" and lets the WebSocket
    mirror deliver the review/apply card. A test asserting on the funnel has to.
    """
    assert task.get("kind"), f"expected a task, got {task}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = client.task(task["id"])
        if current["status"] in ("done", "failed"):
            return current
        time.sleep(0.02)
    raise AssertionError(f"task {task['id']} did not finish within {timeout}s")


def tailor(client: JobPilotClient, job_id: str) -> dict:
    return finish(client, client.tailor(job_id))


def apply_(client: JobPilotClient, job_id: str) -> dict:
    return finish(client, client.apply(job_id))


@pytest.fixture
def client(session_factory, worker_db, tmp_path, monkeypatch):
    """A JobPilotClient wired to the in-process API — no server, real routes."""
    monkeypatch.setattr(
        "jobpilot.tailor.service.compile_document",
        lambda doc, scope: type("R", (), {"pages": 1})(),
    )
    monkeypatch.setattr(
        "jobpilot.apply.dispatcher.build_dir", lambda scope: tmp_path / scope_slug(scope)
    )
    cfg = ApplyCfg(email=EmailCfg(enabled=True, from_addr="me@example.com", dry_run=True))
    monkeypatch.setattr(
        "jobpilot.apply.dispatcher.get_config", lambda: type("C", (), {"apply": cfg})()
    )

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
                    title="Backend Engineer (Java)",
                    company="ACME Corp",
                    location="Ho Chi Minh City",
                    salary="1000-2000 USD",
                    level="fresher",
                    status=JobStatus.DISCOVERED,
                    match_score=0.8,
                    url="https://itviec.com/jobs/1",
                    apply_channel="email",
                    apply_target="hr@acme.com",
                    payload={"skills": ["Java", "Spring Boot"], "description_md": "Java"},
                ),
                Job(
                    id="itviec:2",
                    source="itviec",
                    title="Java Dev",
                    company="BetaCo",
                    status=JobStatus.DISCOVERED,
                    payload={"skills": [], "description_md": "Java"},
                ),
            ]
        )
        s.commit()

    pdf = tmp_path / scope_slug("itviec:1") / "cv.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\n")

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_engine] = lambda: FixtureEngine(plan=PLAN)
    fastapi_app.dependency_overrides[get_letter_engine] = lambda: None

    http = TestClient(fastapi_app)
    c = JobPilotClient(
        base_url="http://testserver",
        token=get_secrets().jobpilot_api_token,
        http_client=http,
    )
    yield c
    c.close()
    http.close()
    fastapi_app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Block Kit shapes — asserted against Slack's own limits
# --------------------------------------------------------------------------- #
def test_check_blocks_accepts_every_builder(client):
    job = client.job("itviec:1")
    client.shortlist("itviec:1")
    tailor(client, "itviec:1")
    review = client.review("itviec:1")

    for blocks in (
        B.job_card(job),
        B.review_card(job, review),
        B.apply_card(job, {"result": "dry_run", "channel": "email", "detail": "x"}),
        B.crawl_card(client.stats()),
        B.error_card("itviec:1", "Apply failed", "SMTP error"),
    ):
        assert B.check_blocks(blocks) == []


def test_check_blocks_catches_oversized_content():
    bad = [
        B.section("x" * 10),
        {"type": "actions", "elements": [{"type": "button", "value": "v"}]},  # no action_id
    ]
    assert any("action_id" in p for p in B.check_blocks(bad))
    assert B.check_blocks([B.section("x")] * 60)[0].startswith("60 blocks")


def test_long_text_is_truncated_not_rejected():
    block = B.section("x" * 5000)
    assert len(block["text"]["text"]) == B.MAX_SECTION_TEXT
    assert B.check_blocks([block]) == []


def test_every_button_action_id_has_a_client_method(client):
    for action_id, method in B.ACTIONS.items():
        assert hasattr(client, method), f"{action_id} -> client.{method} missing"


def test_job_card_flags_a_fresh_job(client):
    job = dict(client.job("itviec:1"), is_fresh=True)
    text = B.job_card(job)[0]["text"]["text"]
    assert text.startswith("*🔥")
    assert "1000-2000 USD" in text and "match 80%" in text


def test_review_card_shows_gaps_and_changes(client):
    client.shortlist("itviec:1")
    tailor(client, "itviec:1")
    blocks = B.review_card(client.job("itviec:1"), client.review("itviec:1"))
    rendered = " ".join(b.get("text", {}).get("text", "") for b in blocks if b["type"] == "section")
    assert "Honors hidden" in rendered
    assert "Kafka" in rendered and "left off deliberately" in rendered


def test_review_card_warns_when_the_cv_spills_to_two_pages(client):
    job = client.job("itviec:1")
    blocks = B.review_card(job, {"version": 1, "match_score": 0.5, "pages": 2, "plan": {}})
    assert "2 pages" in blocks[0]["text"]["text"]


def test_apply_card_never_calls_a_dry_run_sent(client):
    job = client.job("itviec:1")
    blocks = B.apply_card(job, {"result": "dry_run", "channel": "email", "detail": "not sent"})
    headline = blocks[0]["text"]["text"]
    assert "not sent" in headline.lower() and "sent*" not in headline.lower().split("\n")[0][:20]


def test_apply_card_surfaces_a_test_redirect(client):
    job = client.job("itviec:1")
    blocks = B.apply_card(
        job,
        {
            "result": "success",
            "channel": "email",
            "detail": "ok",
            "email": {
                "to": "me@example.com",
                "intended_to": "hr@acme.com",
                "redirected": True,
                "attachments": ["cv.pdf"],
            },
        },
    )
    rendered = str(blocks)
    assert "test redirect" in rendered and "hr@acme.com" in rendered


def test_apply_card_offers_confirm_only_when_waiting(client):
    job = client.job("itviec:1")
    waiting = B.apply_card(job, {"result": "awaiting_user", "channel": "portal", "detail": ""})
    done = B.apply_card(job, {"result": "success", "channel": "email", "detail": ""})
    assert "job_confirm_submit" in str(waiting)
    assert "job_confirm_submit" not in str(done)


# --------------------------------------------------------------------------- #
# Client — the same endpoints the dashboard uses
# --------------------------------------------------------------------------- #
def test_client_drives_the_whole_funnel(client):
    assert client.health()["status"] == "ok"
    assert client.job("itviec:1")["status"] == "DISCOVERED"

    client.shortlist("itviec:1")
    assert client.job("itviec:1")["status"] == "SHORTLISTED"

    tailor(client, "itviec:1")
    assert client.job("itviec:1")["status"] == "REVIEW"

    client.approve("itviec:1")
    assert client.job("itviec:1")["status"] == "APPROVED"

    task = apply_(client, "itviec:1")
    assert task["result"]["result"] == "dry_run"
    # A dry run must not pretend the job was submitted, in Slack either.
    assert client.job("itviec:1")["status"] == "APPROVED"


def test_client_surfaces_api_errors_with_a_readable_detail(client):
    with pytest.raises(ApiError) as exc:
        client.approve("itviec:1")  # still DISCOVERED
    assert exc.value.status == 409
    assert "DISCOVERED" in exc.value.detail


def test_client_404_for_unknown_job(client):
    with pytest.raises(ApiError) as exc:
        client.job("nope:1")
    assert exc.value.status == 404


def test_client_rejects_a_bad_token():
    with TestClient(fastapi_app) as http:
        bad = JobPilotClient(base_url="http://testserver", token="wrong", http_client=http)
        with pytest.raises(ApiError) as exc:
            bad.jobs()
        assert exc.value.status == 401


def test_job_ids_with_colons_survive_the_url(client):
    assert JobPilotClient._job_path("itviec:2156537") == "/jobs/itviec:2156537"
    assert client.job("itviec:2")["id"] == "itviec:2"


# --------------------------------------------------------------------------- #
# Event mapping
# --------------------------------------------------------------------------- #
def test_tailor_done_becomes_a_review_message(client):
    client.shortlist("itviec:1")
    tailor(client, "itviec:1")
    note = notification_for({"type": "tailor_done", "id": "itviec:1"}, client)
    assert note and note.kind == "review"
    assert "ACME Corp" in note.text or "Backend Engineer" in note.text
    assert B.check_blocks(note.blocks) == []


def test_apply_done_becomes_an_apply_message(client):
    client.shortlist("itviec:1")
    tailor(client, "itviec:1")
    client.approve("itviec:1")
    apply_(client, "itviec:1")
    note = notification_for({"type": "apply_done", "id": "itviec:1"}, client)
    assert note and note.kind == "apply"
    assert "dry_run" in note.text
    assert B.check_blocks(note.blocks) == []


def test_the_bot_asks_the_server_for_one_application_not_the_whole_board(client):
    """It used to pull `/applications` and scan it in Python for the matching
    `job_id`. That was merely wasteful until the endpoint grew a page size —
    then the row it wanted could sit on page 2, and the bot would report "no
    application" for a job it had just applied to, filling the card with a
    generic fallback instead of the real outcome."""
    client.shortlist("itviec:1")
    tailor(client, "itviec:1")
    client.approve("itviec:1")
    apply_(client, "itviec:1")

    row = client.application_for("itviec:1")
    assert row is not None and row["job_id"] == "itviec:1"
    assert client.application_for("itviec:does-not-exist") is None

    # The filter is the server's job: asking for one job must not depend on
    # that job landing inside the default window.
    assert client.applications(job_id="itviec:1", limit=1) == [row]


def test_routine_transitions_stay_quiet(client):
    """Mirroring every status change would make the channel unusable."""
    for status in ("DISCOVERED", "SHORTLISTED", "TAILORING", "REVIEW", "APPROVED", "SUBMITTING"):
        assert (
            notification_for({"type": "job_updated", "id": "itviec:1", "status": status}, client)
            is None
        )
    assert notification_for({"type": "hello", "version": "0.1.0"}, client) is None
    assert notification_for({"type": "cv_updated", "scope": "master"}, client) is None


def test_an_employer_moving_is_worth_a_message(client):
    """Phase 18. An interview or an offer is exactly the thing you want to hear
    about while away from the dashboard."""
    note = notification_for(
        {
            "type": "outcome_recorded",
            "application_id": 1,
            "job_id": "itviec:1",
            "event_type": "interview",
            "label": "Round 1",
        },
        client,
    )
    assert note and note.kind == "outcome"
    assert "Interview" in note.text and "ACME Corp" in note.text
    assert B.check_blocks(note.blocks) == []


def test_outcomes_you_typed_yourself_stay_quiet(client):
    """``replied``/``withdrawn``/``ghosted`` are things you just entered by
    hand. Echoing them back is how a channel becomes noise you mute."""
    for event_type in ("replied", "withdrawn", "ghosted"):
        assert (
            notification_for(
                {"type": "outcome_recorded", "job_id": "itviec:1", "event_type": event_type},
                client,
            )
            is None
        )


def test_failures_are_reported(client):
    client.shortlist("itviec:1")
    tailor(client, "itviec:1")
    client.approve("itviec:1")
    client.report_failure  # noqa: B018 - referenced for clarity
    apply_(client, "itviec:1")
    note = notification_for({"type": "job_updated", "id": "itviec:1", "status": "FAILED"}, client)
    assert note and note.kind == "error"


def test_outcome_adapter_reads_an_application_row():
    row = {
        "result": "awaiting_user",
        "channel": "portal",
        "error_msg": None,
        "meta": {"handoff": {"url": "https://x", "note": "submit it yourself", "fields": {}}},
    }
    outcome = outcome_from_application(row)
    assert outcome["detail"] == "submit it yourself"
    assert outcome["handoff"]["url"] == "https://x"


def test_digest_summarises_then_lists_fresh_jobs(client):
    notes = digest(client, limit=5)
    assert notes[0].kind == "crawl"
    assert {n.job_id for n in notes[1:]} == {"itviec:1", "itviec:2"}
    for note in notes:
        assert B.check_blocks(note.blocks) == []


# --------------------------------------------------------------------------- #
# Degradation
# --------------------------------------------------------------------------- #
def test_missing_tokens_produce_a_readable_error(monkeypatch):
    from jobpilot.config import Secrets
    from jobpilot.slack.app import SlackConfig, SlackNotConfigured

    # All three forced empty. Overriding only one let the other two fall through
    # to the developer's real .env, so this test passed or failed depending on
    # whether the machine running it happened to have Slack configured.
    monkeypatch.setattr(
        "jobpilot.slack.app.get_secrets",
        lambda: Secrets(slack_bot_token="", slack_app_token="", slack_channel_id=""),
    )
    with pytest.raises(SlackNotConfigured) as exc:
        SlackConfig.from_secrets()
    for name in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_CHANNEL_ID"):
        assert name in str(exc.value)


def test_slack_module_imports_without_the_sdk():
    """The package must import on a machine that never installed slack-bolt."""
    import jobpilot.slack.app as slack_app

    assert callable(slack_app.run)
