"""Phase 8: the task queue, ops endpoints, and the settings overlay."""

from __future__ import annotations

import asyncio
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from jobpilot.api.deps import get_db
from jobpilot.api.main import app as fastapi_app
from jobpilot.config import Config, deep_merge, get_secrets
from jobpilot.orchestrator import DONE, FAILED, RUNNING, TaskQueue
from jobpilot.store.models import Run
from jobpilot.timeutil import vn_now

AUTH = {"X-API-Token": get_secrets().jobpilot_api_token}


@pytest.fixture
def q():
    queue = TaskQueue(max_workers=1, history=5)
    yield queue
    queue.shutdown(wait=True)


def _wait(queue: TaskQueue, task_id: str, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = queue.get(task_id)
        if task and task.status in (DONE, FAILED):
            return task
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not finish in {timeout}s")


# --------------------------------------------------------------------------- #
# TaskQueue
# --------------------------------------------------------------------------- #
def test_task_runs_and_reports_its_result(q):
    task = q.submit("crawl", lambda progress: {"inserted": 3}, label="test")
    done = _wait(q, task.id)
    assert done.status == DONE and done.result == {"inserted": 3}
    assert done.started_at and done.finished_at


def test_progress_messages_are_recorded(q):
    def body(progress):
        progress("step one")
        progress("step two")
        return {}

    assert _wait(q, q.submit("crawl", body, label="test").id).progress == "step two"


def test_a_failing_task_is_data_not_a_crash(q):
    """A failure has to reach the Runs page, so nothing escapes the worker."""

    def boom(progress):
        raise RuntimeError("site is down")

    task = _wait(q, q.submit("crawl", boom, label="test").id)
    assert task.status == FAILED
    assert task.error == "RuntimeError: site is down"
    assert task.finished_at is not None


def test_status_is_written_last_so_finished_tasks_are_fully_populated(q):
    """A watcher polling on status must never catch a half-written task."""
    for body, expect in ((lambda p: {"n": 1}, DONE), (lambda p: 1 / 0, FAILED)):
        task = _wait(q, q.submit("crawl", body, label="x").id)
        assert task.status == expect
        assert task.finished_at is not None
        assert (task.error is not None) == (expect == FAILED)


def test_tasks_are_serialised_by_the_single_worker(q):
    """Overlapping Docker builds and browsers would fight; queued must mean queued."""
    order = []

    def slow(name):
        def body(progress):
            order.append(f"{name}-start")
            time.sleep(0.05)
            order.append(f"{name}-end")
            return {}

        return body

    a = q.submit("crawl", slow("a"), label="a")
    b = q.submit("crawl", slow("b"), label="b")
    _wait(q, a.id)
    _wait(q, b.id)
    assert order == ["a-start", "a-end", "b-start", "b-end"]


def test_history_is_bounded_but_never_drops_pending_work(q):
    """Evicting a queued task would make it unobservable, so only finished ones go."""
    ids = []
    for i in range(8):
        task = q.submit("crawl", lambda p: {}, label=str(i))
        ids.append(task.id)
        _wait(q, task.id)
    assert len(q.list(limit=100)) == 5
    assert q.get(ids[0]) is None  # oldest finished task evicted
    assert q.get(ids[-1]) is not None


def test_listing_is_newest_first_and_filterable(q):
    _wait(q, q.submit("crawl", lambda p: {}, label="c").id)
    _wait(q, q.submit("tailor", lambda p: {}, label="t").id)
    assert [t.kind for t in q.list()] == ["tailor", "crawl"]
    assert [t.label for t in q.list(kind="crawl")] == ["c"]


def test_active_reports_only_unfinished(q):
    task = _wait(q, q.submit("crawl", lambda p: {}, label="x").id)
    assert task.status == DONE
    assert q.active() == []


def test_events_reach_a_bound_listener():
    """Worker threads must be able to publish onto the API's event loop."""
    received: list[dict] = []

    async def main():
        queue = TaskQueue(max_workers=1)

        async def listener(payload):
            received.append(payload)

        queue.bind(asyncio.get_running_loop(), listener)
        task = queue.submit("crawl", lambda p: p("working") or {"ok": True}, label="x")
        for _ in range(500):
            await asyncio.sleep(0.01)
            if queue.get(task.id).status == DONE:
                break
        await asyncio.sleep(0.1)  # let the queued coroutines drain
        queue.shutdown(wait=True)

    asyncio.run(main())
    kinds = [p["type"] for p in received]
    assert kinds and set(kinds) == {"task_updated"}
    statuses = [p["task"]["status"] for p in received]
    assert RUNNING in statuses and DONE in statuses
    assert any(p["task"]["progress"] == "working" for p in received)


def test_an_unbound_queue_runs_silently(q):
    """The CLI uses the queue without an event loop; that must not blow up."""
    assert _wait(q, q.submit("crawl", lambda p: p("hi") or {}, label="x").id).status == DONE


# --------------------------------------------------------------------------- #
# Settings overlay
# --------------------------------------------------------------------------- #
def test_deep_merge_only_overrides_what_it_sets():
    base = {"crawl": {"jobs_per_site": 10, "fresh_hours": 48}, "cv": {"theme": "red"}}
    merged = deep_merge(base, {"crawl": {"fresh_hours": 24}})
    assert merged == {"crawl": {"jobs_per_site": 10, "fresh_hours": 24}, "cv": {"theme": "red"}}


def test_overlay_is_merged_over_the_base(tmp_path, monkeypatch):
    from jobpilot import config as config_mod

    base = tmp_path / "config.yaml"
    base.write_text(yaml.safe_dump({"crawl": {"jobs_per_site": 10, "fresh_hours": 48}}))
    local = tmp_path / "config.local.yaml"
    local.write_text(yaml.safe_dump({"crawl": {"fresh_hours": 12}}))
    monkeypatch.setattr(config_mod, "LOCAL_CONFIG_PATH", local)
    config_mod.get_config.cache_clear()

    cfg = config_mod.get_config(base)
    assert cfg.crawl.fresh_hours == 12  # overlay wins
    assert cfg.crawl.jobs_per_site == 10  # base survives
    config_mod.get_config.cache_clear()


def test_saving_settings_never_touches_the_commented_base(tmp_path, monkeypatch):
    from jobpilot import config as config_mod

    base = tmp_path / "config.yaml"
    original = "# a load-bearing comment\ncrawl:\n  fresh_hours: 48\n"
    base.write_text(original)
    local = tmp_path / "config.local.yaml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", base)
    monkeypatch.setattr(config_mod, "LOCAL_CONFIG_PATH", local)
    config_mod.get_config.cache_clear()

    cfg = config_mod.save_local_config({"crawl": {"fresh_hours": 24}})
    assert cfg.crawl.fresh_hours == 24
    assert base.read_text() == original  # comments intact
    assert "fresh_hours: 24" in local.read_text()
    config_mod.get_config.cache_clear()


def test_an_invalid_patch_is_rejected_before_it_is_written(tmp_path, monkeypatch):
    from jobpilot import config as config_mod

    base = tmp_path / "config.yaml"
    base.write_text(yaml.safe_dump({"crawl": {"fresh_hours": 48}}))
    local = tmp_path / "config.local.yaml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", base)
    monkeypatch.setattr(config_mod, "LOCAL_CONFIG_PATH", local)
    config_mod.get_config.cache_clear()

    with pytest.raises(Exception):
        config_mod.save_local_config({"crawl": {"fresh_hours": "not a number"}})
    assert not local.exists()  # nothing written — the app can still start
    config_mod.get_config.cache_clear()


# --------------------------------------------------------------------------- #
# Ops endpoints
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(session_factory, monkeypatch):
    test_queue = TaskQueue(max_workers=1)
    monkeypatch.setattr("jobpilot.api.routes.ops.queue", test_queue)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    with session_factory() as s:
        s.add_all(
            [
                Run(kind="crawl", started_at=vn_now(), finished_at=vn_now(), stats={"inserted": 4}),
                Run(kind="tailor", started_at=vn_now(), finished_at=vn_now(), stats={"ok": True}),
            ]
        )
        s.commit()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    c = TestClient(fastapi_app)
    yield c, test_queue
    fastapi_app.dependency_overrides.clear()
    test_queue.shutdown(wait=True)


def test_ops_requires_a_token(client):
    c, _ = client
    assert c.get("/tasks").status_code == 401
    assert c.get("/runs").status_code == 401
    assert c.post("/crawl").status_code == 401


def test_crawl_returns_202_and_a_task(client, monkeypatch):
    c, q = client
    monkeypatch.setattr("jobpilot.api.routes.ops.crawl_body", lambda **kw: (lambda p: {"ok": True}))
    r = c.post("/crawl", headers=AUTH)
    assert r.status_code == 202
    body = r.json()
    assert body["kind"] == "crawl" and body["status"] in ("queued", "running", "done")
    assert _wait(q, body["id"]).result == {"ok": True}


def test_a_second_crawl_is_refused_while_one_runs(client, monkeypatch):
    """Two crawls would race the same sites and trip their rate limits."""
    c, q = client
    monkeypatch.setattr(
        "jobpilot.api.routes.ops.crawl_body", lambda **kw: (lambda p: time.sleep(0.4) or {})
    )
    first = c.post("/crawl", headers=AUTH)
    assert first.status_code == 202
    second = c.post("/crawl", headers=AUTH)
    assert second.status_code == 409 and "already" in second.json()["detail"]
    _wait(q, first.json()["id"])


def test_task_can_be_polled_and_404s_when_unknown(client, monkeypatch):
    c, q = client
    monkeypatch.setattr("jobpilot.api.routes.ops.crawl_body", lambda **kw: (lambda p: {"n": 1}))
    task_id = c.post("/crawl", headers=AUTH).json()["id"]
    _wait(q, task_id)
    assert c.get(f"/tasks/{task_id}", headers=AUTH).json()["result"] == {"n": 1}
    assert c.get("/tasks/nope", headers=AUTH).status_code == 404


def test_a_failed_crawl_surfaces_its_reason(client, monkeypatch):
    c, q = client

    def boom(**kw):
        def body(p):
            raise RuntimeError("ITviec unreachable")

        return body

    monkeypatch.setattr("jobpilot.api.routes.ops.crawl_body", boom)
    task_id = c.post("/crawl", headers=AUTH).json()["id"]
    _wait(q, task_id)
    body = c.get(f"/tasks/{task_id}", headers=AUTH).json()
    assert body["status"] == "failed" and "ITviec unreachable" in body["error"]


def test_runs_history_is_newest_first_and_filterable(client):
    c, _ = client
    rows = c.get("/runs", headers=AUTH).json()
    assert [r["kind"] for r in rows] == ["tailor", "crawl"]
    assert c.get("/runs?kind=crawl", headers=AUTH).json()[0]["stats"] == {"inserted": 4}


def test_settings_round_trip(client, tmp_path, monkeypatch):
    from jobpilot import config as config_mod

    base = tmp_path / "config.yaml"
    base.write_text(yaml.safe_dump(Config().model_dump()))
    monkeypatch.setattr(config_mod, "CONFIG_PATH", base)
    monkeypatch.setattr(config_mod, "LOCAL_CONFIG_PATH", tmp_path / "config.local.yaml")
    config_mod.get_config.cache_clear()

    c, _ = client
    assert c.get("/settings", headers=AUTH).json()["crawl"]["fresh_hours"] == 48
    r = c.put("/settings", headers=AUTH, json={"crawl": {"fresh_hours": 24}})
    assert r.status_code == 200 and r.json()["crawl"]["fresh_hours"] == 24
    assert c.get("/settings", headers=AUTH).json()["crawl"]["fresh_hours"] == 24
    config_mod.get_config.cache_clear()


def test_settings_reject_an_empty_or_invalid_patch(client, tmp_path, monkeypatch):
    from jobpilot import config as config_mod

    base = tmp_path / "config.yaml"
    base.write_text(yaml.safe_dump(Config().model_dump()))
    monkeypatch.setattr(config_mod, "CONFIG_PATH", base)
    monkeypatch.setattr(config_mod, "LOCAL_CONFIG_PATH", tmp_path / "config.local.yaml")
    config_mod.get_config.cache_clear()

    c, _ = client
    assert c.put("/settings", headers=AUTH, json={}).status_code == 422
    bad = c.put("/settings", headers=AUTH, json={"crawl": {"fresh_hours": "soon"}})
    assert bad.status_code == 422 and "invalid settings" in bad.json()["detail"]
    config_mod.get_config.cache_clear()


def test_settings_never_leak_secrets(client):
    c, _ = client
    blob = str(c.get("/settings", headers=AUTH).json()).lower()
    for word in ("password", "api_key", "refresh_token", "smtp_user"):
        assert word not in blob


# --- crawl scoping: sources / limit / suggestions --------------------------- #


def test_build_scrapers_only_narrows_never_widens():
    """`only` can subtract from the enabled set but cannot enable a source that
    Settings has switched off — Settings stays the single gate."""
    from jobpilot.config import Config
    from jobpilot.crawler.registry import build_scrapers

    cfg = Config.model_validate(
        {
            "sources": [
                {"key": "itviec", "enabled": True},
                {"key": "linkedin", "enabled": True},
                {"key": "topcv", "enabled": False},
            ]
        }
    )
    assert {s.source for s in build_scrapers(cfg)} == {"itviec", "linkedin"}
    assert {s.source for s in build_scrapers(cfg, only=["itviec"])} == {"itviec"}
    # topcv is disabled in config, so asking for it yields nothing at all.
    assert build_scrapers(cfg, only=["topcv"]) == []


def test_suggest_keywords_reads_stack_and_role_not_prose():
    from jobpilot.crawler.suggest import suggest_keywords
    from jobpilot.cv.schema import BulletItem, BulletsSection, CvDocument, Entry, ExperienceSection

    doc = CvDocument(
        sections=[
            ExperienceSection(
                key="experience",
                title="Work Experience",
                entries=[
                    Entry(
                        title="FPT Software, Junior Software Engineer - Backend",
                        items=["Did a thing that mentions Nonsense."],
                        tech_stack=["Java", "Spring Boot"],
                    )
                ],
            ),
            BulletsSection(
                key="skills",
                title="Skills",
                items=[BulletItem(label="Backend", text="Java, PostgreSQL, Docker")],
            ),
            BulletsSection(
                key="honors",
                title="Honors",
                items=[BulletItem(text="Employee of the Year, Excellent Teamwork")],
            ),
        ]
    )
    out = suggest_keywords(doc)

    # Java appears in both the stack and the Skills line, so it outranks singles.
    assert out["tech"][0] == "Java"
    assert {"Spring Boot", "PostgreSQL", "Docker"} <= set(out["tech"])
    # Seniority dropped, company dropped, prose never considered.
    assert out["roles"] == ["Software Engineer Backend"]
    assert not any("Employee of the Year" in t for t in out["tech"])
