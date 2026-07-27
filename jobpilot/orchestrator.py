"""In-process task queue for the long-running work (PLAN.md §5.5).

Crawling walks several sites behind a rate limiter and takes minutes; it cannot
run inside a request. This runs it on a worker thread, tracks its state, and
pushes progress to the dashboard over the existing WebSocket.

**One worker by default.** This is a single-user tool on a laptop that also runs
Docker and a browser — fanning out would fight for the same resources, and a
serial queue makes "queued" mean something. Raise ``max_workers`` if that ever
stops being true.

Each task body opens its own DB session: SQLAlchemy sessions are not thread-safe,
and sharing a request's session with a thread that outlives the request is how
you get mystifying bugs.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import traceback
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from jobpilot.timeutil import vn_now

log = logging.getLogger("jobpilot.orchestrator")

# Progress reporter handed to every task body.
Progress = Callable[[str], None]
TaskBody = Callable[[Progress], dict]

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"


@dataclass
class Task:
    id: str
    kind: str  # crawl | tailor | apply
    label: str
    job_id: str | None = None
    status: str = QUEUED
    progress: str = ""
    result: dict = field(default_factory=dict)
    error: str | None = None
    created_at: datetime = field(default_factory=vn_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class TaskQueue:
    """Submit work, watch it, and get told when it moves."""

    def __init__(self, max_workers: int = 1, history: int = 50) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="jobpilot")
        self._tasks: OrderedDict[str, Task] = OrderedDict()
        self._history = history
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listener: Callable[[dict], Any] | None = None

    # ------------------------------------------------------------------ #
    # Wiring
    # ------------------------------------------------------------------ #
    def bind(self, loop: asyncio.AbstractEventLoop, listener: Callable[[dict], Any]) -> None:
        """Attach the API's event loop and broadcaster so worker threads can
        publish progress. Called once on app startup; an unbound queue just runs
        silently, which is what the CLI wants."""
        self._loop = loop
        self._listener = listener

    def _emit(self, task: Task) -> None:
        if self._loop is None or self._listener is None:
            return
        payload = {"type": "task_updated", "task": task.to_dict()}
        try:
            asyncio.run_coroutine_threadsafe(self._listener(payload), self._loop)
        except RuntimeError:  # loop already closed during shutdown
            pass

    # ------------------------------------------------------------------ #
    # Submission
    # ------------------------------------------------------------------ #
    def submit(self, kind: str, body: TaskBody, *, label: str, job_id: str | None = None) -> Task:
        task = Task(id=uuid.uuid4().hex[:12], kind=kind, label=label, job_id=job_id)
        with self._lock:
            self._tasks[task.id] = task
            self._evict_finished()
        self._emit(task)
        self._executor.submit(self._run, task, body)
        return task

    def _evict_finished(self) -> None:
        """Trim history oldest-first, but never drop a task that hasn't run yet —
        losing a queued task would make it unobservable and un-pollable."""
        over = len(self._tasks) - self._history
        if over <= 0:
            return
        for task_id, task in list(self._tasks.items()):
            if over <= 0:
                break
            if task.status in (DONE, FAILED):
                del self._tasks[task_id]
                over -= 1

    def _run(self, task: Task, body: TaskBody) -> None:
        task.status = RUNNING
        task.started_at = vn_now()
        self._emit(task)

        def progress(message: str) -> None:
            task.progress = message
            self._emit(task)

        result: dict = {}
        error: str | None = None
        try:
            result = body(progress) or {}
        except Exception as exc:
            # A failed task is data, not a crash: it has to show up on the Runs
            # page with a cause, so nothing escapes this thread.
            error = f"{type(exc).__name__}: {exc}"
            log.warning("task %s (%s) failed: %s", task.id, task.kind, error)
            log.debug("%s", traceback.format_exc())

        # `status` is the completion signal every consumer polls on, so it is
        # written last — otherwise a watcher can see a finished task whose
        # result and finished_at aren't populated yet.
        task.result, task.error = result, error
        task.finished_at = vn_now()
        task.status = FAILED if error else DONE
        self._emit(task)

    # ------------------------------------------------------------------ #
    # Reading
    # ------------------------------------------------------------------ #
    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list(self, limit: int = 50, kind: str | None = None) -> list[Task]:
        """Newest first."""
        with self._lock:
            tasks = list(self._tasks.values())
        if kind:
            tasks = [t for t in tasks if t.kind == kind]
        return list(reversed(tasks))[:limit]

    def active(self, kind: str | None = None) -> list[Task]:
        return [t for t in self.list(kind=kind) if t.status in (QUEUED, RUNNING)]

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=not wait)


# Process-wide queue. The API binds it on startup; the CLI uses it unbound.
queue = TaskQueue()


# --------------------------------------------------------------------------- #
# Task bodies
# --------------------------------------------------------------------------- #
def crawl_body(
    query: str | None = None,
    respect_robots: bool = True,
    sources: list[str] | None = None,
    limit: int | None = None,
) -> TaskBody:
    """A crawl over the enabled sources, summarised per site.

    ``sources`` and ``limit`` scope one run only; neither is written back to
    config, so a narrow one-off crawl can't quietly become the new default.
    """

    def body(progress: Progress) -> dict:
        from jobpilot.config import get_config
        from jobpilot.crawler.pipeline import default_query, run_crawl
        from jobpilot.crawler.registry import build_scrapers
        from jobpilot.store.db import session_scope

        cfg = get_config()
        scrapers = build_scrapers(cfg, respect_robots=respect_robots, only=sources)
        if not scrapers:
            asked = f" matching {sources}" if sources else ""
            raise RuntimeError(
                f"no enabled source{asked} has a registered scraper — check `sources` in Settings"
            )

        resolved = query or default_query(cfg)
        progress(f"crawling {', '.join(s.source for s in scrapers)} for {resolved!r}")
        with session_scope() as db:
            report = run_crawl(scrapers, cfg, db, query=resolved, limit=limit)

            sites = [
                {
                    "source": site.source,
                    "ok": site.ok,
                    "error": site.error,
                    "fetched": site.stats.fetched,
                    "inserted": site.stats.inserted,
                    "updated": site.stats.updated,
                    "duplicates": site.stats.duplicates,
                    "filtered": site.stats.filtered,
                    "fresh": site.stats.fresh,
                }
                for site in report.sites
            ]
            t = report.totals
            progress(f"done — {t.inserted} new, {t.updated} updated")
            return {
                "run_id": report.run_id,
                "query": resolved,
                "sites": sites,
                "totals": {
                    "inserted": t.inserted,
                    "updated": t.updated,
                    "duplicates": t.duplicates,
                    "fresh": t.fresh,
                    "filtered": t.filtered,
                },
            }

    return body
