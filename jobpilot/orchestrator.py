"""In-process task queue for the long-running work (PLAN.md §5.5).

Crawling walks several sites behind a rate limiter and takes minutes; tailoring
is a Claude call plus a Docker LaTeX build; applying may write a cover letter and
talk to an SMTP server. None of them can answer inside a request. This runs them
on a worker thread, tracks their state, and pushes progress to the dashboard over
the existing WebSocket.

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


class TaskBusy(RuntimeError):
    """An exclusive task for this job is already queued or running."""

    def __init__(self, task: "Task") -> None:
        super().__init__(
            f"another task for this job is already {task.status} ({task.kind} {task.id})"
        )
        self.task = task


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
    # Exception class name. The message alone can't tell "the agent tried to
    # claim a skill you don't have" (GuardrailViolation — a truthfulness event
    # the UI must not bury) from "LaTeX wouldn't compile".
    error_kind: str | None = None
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
            "error_kind": self.error_kind,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class TaskQueue:
    """Submit work, watch it, and get told when it moves."""

    def __init__(self, max_workers: int = 1, history: int = 50) -> None:
        self._max_workers = max_workers
        self._executor: ThreadPoolExecutor | None = None
        self._tasks: OrderedDict[str, Task] = OrderedDict()
        self._history = history
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listener: Callable[[dict], Any] | None = None

    def _pool_locked(self) -> ThreadPoolExecutor:
        """The worker pool, built on first use and rebuilt after a shutdown.
        **Caller must hold ``self._lock``.**

        This queue is a process-wide singleton whose lifetime is tied to the
        API's lifespan, and a ``ThreadPoolExecutor`` cannot be restarted once
        shut down. Without rebuilding, a second lifespan in the same process
        leaves every later task sitting in ``queued`` forever — visible in the
        UI, never running, with nothing to say why.
        """
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers, thread_name_prefix="jobpilot"
            )
        return self._executor

    def _active_locked(self, job_id: str) -> Task | None:
        return next(
            (
                t
                for t in self._tasks.values()
                if t.job_id == job_id and t.status in (QUEUED, RUNNING)
            ),
            None,
        )

    # ------------------------------------------------------------------ #
    # Wiring
    # ------------------------------------------------------------------ #
    def bind(self, loop: asyncio.AbstractEventLoop, listener: Callable[[dict], Any]) -> None:
        """Attach the API's event loop and broadcaster so worker threads can
        publish progress. Called once on app startup; an unbound queue just runs
        silently, which is what the CLI wants."""
        self._loop = loop
        self._listener = listener

    def publish(self, message: dict) -> None:
        """Broadcast one event from a worker thread.

        Task bodies use this for the domain events the dashboard and Slack
        listen to (``job_updated``, ``tailor_done``, ``apply_done``) — the
        routes can no longer send them, because they return before the work
        starts. A no-op when the queue is unbound, which is what the CLI wants.
        """
        if self._loop is None or self._listener is None:
            return
        coro = self._listener(message)
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError:  # loop already closed during shutdown
            coro.close()  # or Python warns about a coroutine that never ran

    def _emit(self, task: Task) -> None:
        self.publish({"type": "task_updated", "task": task.to_dict()})

    # ------------------------------------------------------------------ #
    # Submission
    # ------------------------------------------------------------------ #
    def submit(
        self,
        kind: str,
        body: TaskBody,
        *,
        label: str,
        job_id: str | None = None,
        exclusive: bool = False,
    ) -> Task:
        """Queue one task.

        ``exclusive`` refuses the submission (``TaskBusy``) when another task for
        the same job is already queued or running. It lives here rather than in
        the callers because the check and the insert have to happen under one
        lock: two requests that both read "nothing running" and then both submit
        would put two tailor rounds in the same build directory.

        Scheduling happens under the lock too, so a concurrent ``shutdown`` can't
        close the pool between building it and using it — that raced into a task
        stuck in ``queued`` forever, which then blocked its job with a permanent
        409.
        """
        task = Task(id=uuid.uuid4().hex[:12], kind=kind, label=label, job_id=job_id)
        with self._lock:
            if exclusive and job_id is not None:
                busy = self._active_locked(job_id)
                if busy is not None:
                    raise TaskBusy(busy)
            pool = self._pool_locked()
            self._tasks[task.id] = task
            self._evict_finished()
            pool.submit(self._run, task, body)
        self._emit(task)
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
        error_kind: str | None = None
        try:
            result = body(progress) or {}
        except Exception as exc:
            # A failed task is data, not a crash: it has to show up on the Runs
            # page with a cause, so nothing escapes this thread.
            error, error_kind = str(exc) or type(exc).__name__, type(exc).__name__
            log.warning("task %s (%s) failed: %s: %s", task.id, task.kind, error_kind, error)
            log.debug("%s", traceback.format_exc())

        # `status` is the completion signal every consumer polls on, so it is
        # written last — otherwise a watcher can see a finished task whose
        # result and finished_at aren't populated yet.
        task.result, task.error, task.error_kind = result, error, error_kind
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

    def active(self, kind: str | None = None, job_id: str | None = None) -> list[Task]:
        tasks = [t for t in self.list(kind=kind) if t.status in (QUEUED, RUNNING)]
        return [t for t in tasks if t.job_id == job_id] if job_id else tasks

    def shutdown(self, wait: bool = False) -> None:
        """Stop the workers. A later ``submit`` builds a fresh pool."""
        with self._lock:
            pool, self._executor = self._executor, None
            # Captured under the same lock that retires the pool, so this is
            # exactly the work that pool was holding. Read afterwards instead
            # and a task submitted to the *replacement* pool could be caught
            # here and marked failed while it happily runs.
            stranded = [] if wait else [t for t in self._tasks.values() if t.status == QUEUED]
        if pool is None:
            return
        pool.shutdown(wait=wait, cancel_futures=not wait)
        # Pending work was cancelled, so say so. Left as "queued" these tasks
        # would claim to be waiting for a worker that no longer exists.
        for task in stranded:
            if task.status != QUEUED:  # a worker picked it up before we got here
                continue
            task.error, task.error_kind = "cancelled — the queue shut down", "Cancelled"
            task.finished_at = vn_now()
            task.status = FAILED
            self._emit(task)


# Process-wide queue. The API binds it on startup; the CLI uses it unbound.
queue = TaskQueue()


# --------------------------------------------------------------------------- #
# Task bodies
#
# Each opens its own session — the request that queued the work is long gone,
# and a SQLAlchemy session is not safe to hand to another thread.
#
# Results are kept deliberately small. ``GET /tasks`` returns the last 50 of
# them at once, and the plan/diff a tailor round produces already has a home in
# ``cv_versions``, served by ``GET /jobs/{id}/review``.
# --------------------------------------------------------------------------- #
def _publish_job_status(job_id: str, *, settle: bool = False) -> None:
    """Tell the dashboard and Slack where the job ended up.

    Read in a fresh session: on the failure path the task's own session has
    already been unwound, and the status the reviewer needs to see was committed
    before the exception surfaced.

    ``settle`` additionally rescues a job left mid-transition. The services move
    a job to TAILORING/SUBMITTING and commit *before* the slow part, and only
    convert that to FAILED for the failures they expect (guardrail, build, SMTP).
    Anything else — a bug, a dropped connection — used to strand the job in a
    status that means "working on it right now" with nothing working on it. The
    task carries the real error; this just stops the dashboard claiming progress
    that isn't happening.
    """
    from jobpilot.store.db import session_scope
    from jobpilot.store.models import Job, JobStatus

    in_flight = {JobStatus.TAILORING, JobStatus.SUBMITTING}
    try:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            if settle and job.status in in_flight:
                log.warning(
                    "job %s left in %s by a failed task — marking FAILED", job_id, job.status.value
                )
                job.status = JobStatus.FAILED
            status = job.status.value
    except Exception:  # never let a notification failure mask the real outcome
        log.debug("could not read status for %s to publish", job_id, exc_info=True)
        return
    queue.publish({"type": "job_updated", "id": job_id, "status": status})


def tailor_body(job_id: str, engine, instruction: str | None = None) -> TaskBody:
    """One tailor round: plan with Claude, guard it, build the PDF.

    ``engine`` is resolved in the request and closed over rather than built
    here, so a test's dependency override still reaches the worker.
    """

    def body(progress: Progress) -> dict:
        from jobpilot.store.db import session_scope
        from jobpilot.tailor import service

        try:
            with session_scope() as db:
                outcome = service.tailor_job(
                    db, job_id, engine, instruction=instruction, progress=progress
                )
        except Exception:
            _publish_job_status(job_id, settle=True)
            raise

        _publish_job_status(job_id)
        queue.publish(
            {
                "type": "tailor_done",
                "id": job_id,
                "version": outcome.version,
                "pages": outcome.pages,
            }
        )
        return {
            "job_id": job_id,
            "version": outcome.version,
            "round": outcome.round,
            "attempts": outcome.attempts,
            "pages": outcome.pages,
            "match_score": outcome.plan.match_score,
            "gaps": len(outcome.plan.gaps()),
        }

    return body


def apply_body(job_id: str, letter_engine=None) -> TaskBody:
    """Dispatch one application to its channel.

    A dispatch that ends in ``result: "failed"`` still completes the task — the
    work ran and wrote an ``Application`` row saying so. The task only fails
    when the dispatcher itself blew up.
    """

    def body(progress: Progress) -> dict:
        from jobpilot.apply import dispatcher
        from jobpilot.store.db import session_scope

        try:
            with session_scope() as db:
                outcome = dispatcher.apply_job(db, job_id, letter_engine, progress=progress)
        except Exception:
            _publish_job_status(job_id, settle=True)
            raise

        _publish_job_status(job_id)
        queue.publish(
            {
                "type": "apply_done",
                "id": job_id,
                "channel": outcome.channel,
                "result": outcome.result,
            }
        )
        return {
            "job_id": job_id,
            "channel": outcome.channel,
            "result": outcome.result,
            "detail": outcome.detail,
            "application_id": outcome.application_id,
        }

    return body


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


def inbox_body(
    classifier=None, since_days: int | None = None, limit: int | None = None
) -> TaskBody:
    """One pass over the mailbox, proposing what the replies mean (Phase 19).

    On the queue rather than in the request for the usual two reasons: it talks
    to an IMAP server and then, for the handful of messages that matched an
    application, to Claude. Neither belongs inside a web request.

    Nothing it writes is final — every proposal lands as a suggestion for the
    board, and only a person turns one into an outcome.
    """

    def body(progress: Progress) -> dict:
        from jobpilot import llm
        from jobpilot.apply.inbox import default_classifier, sync_inbox
        from jobpilot.config import get_config, get_secrets
        from jobpilot.crawler.mailbox import ImapMailbox
        from jobpilot.store.db import session_scope

        cfg = get_config()
        blocker = cfg.apply.inbox_blocker() or llm.blocker("classify")
        if blocker:
            raise RuntimeError(blocker)

        engine = classifier or default_classifier()
        mailbox = ImapMailbox(get_secrets(), folder=cfg.apply.inbox.folder)
        progress(f"opening {cfg.apply.inbox.folder}")
        with session_scope() as db:
            report = sync_inbox(
                db,
                mailbox=mailbox,
                classifier=engine,
                since_days=since_days or cfg.apply.inbox.since_days,
                limit=limit or cfg.apply.inbox.limit,
                progress=progress,
            )
        progress(f"done — {report.suggested} to look at from {report.scanned} message(s) read")
        return report.as_dict()

    return body
