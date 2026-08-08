"""Recording what each model call cost, in one place.

Three engines, one recorder. The alternative — each engine writing its own rows
— is how the two counters in ``/stats`` came to need a paragraph of explanation
in CLAUDE.md, and this is the moment to not do that again.

The unit is a **round**, not a task: a tailor that needed the corrective retry
writes two rows, both marked with how the task ended. That keeps the two
questions people actually ask — *what does this backend cost me* and *how often
does it get it right first time* — answerable from one table without a join.

Recording is telemetry, and telemetry never breaks the work it measures. Every
write is best-effort: if the database is unreachable, or the row is malformed,
the tailor still returns a CV.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from jobpilot.llm.base import Usage

log = logging.getLogger(__name__)


@dataclass
class CallLog:
    """Accumulates the rounds of one task, then writes them on exit."""

    task: str
    job_id: str | None = None
    application_id: int | None = None
    rounds: list[Usage] = field(default_factory=list)
    #: Set by the engine once the guardrails have accepted an answer. Default
    #: False so a crash mid-task records as a failure rather than as a success
    #: nobody got.
    accepted: bool = False
    error: str | None = None

    def add(self, usage: Usage) -> Usage:
        self.rounds.append(usage)
        return usage

    def add_from(self, completion):
        """Bank one round's cost and hand back the answer.

        Shaped so the engines read as ``plan = usage.add_from(self._ask(...))``:
        the accounting sits on the line that produced the thing being accounted
        for, which is the only placement that stays correct when someone later
        adds a third round.
        """
        self.add(completion.usage)
        return completion.value

    def succeeded(self) -> None:
        self.accepted = True

    @property
    def attempts(self) -> int:
        return len(self.rounds)


@contextmanager
def call_log(
    task: str, *, job_id: str | None = None, application_id: int | None = None
) -> Iterator[CallLog]:
    """Collect the rounds of one task and persist them, however it ends."""
    from jobpilot.llm.redact import redact

    entry = CallLog(task=task, job_id=job_id, application_id=application_id)
    try:
        yield entry
    except Exception as exc:
        # Scrubbed again here, not only in ``LlmError``: what lands in this
        # column may be any exception an SDK raised, and this is the last point
        # before it becomes a durable row.
        entry.error = redact(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        record(entry)


def record(entry: CallLog) -> None:
    """Write one row per round. Never raises.

    Tried twice: once with the job/application links, and if that fails, once
    without them. The links are foreign keys, so anything that makes them
    dangle — a job deleted between the call and the write, a benchmark driving a
    synthetic application — would otherwise cost the whole measurement rather
    than just the link. Losing what a call cost because of who it was *for* is
    the wrong trade, and it went unnoticed the first time precisely because this
    function swallows its own failures.
    """
    if not entry.rounds and not entry.error:
        return
    if _write(entry, linked=True):
        return
    if _write(entry, linked=False):
        log.warning("recorded llm usage for %s without its job/application link", entry.task)


def _write(entry: CallLog, *, linked: bool) -> bool:
    try:
        from jobpilot.store.db import session_scope
        from jobpilot.store.models import LlmCall

        job_id = entry.job_id if linked else None
        application_id = entry.application_id if linked else None
        with session_scope() as db:
            for index, usage in enumerate(entry.rounds, start=1):
                db.add(
                    LlmCall(
                        task=entry.task,
                        provider=usage.provider,
                        model=usage.model,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        cached_input_tokens=usage.cached_input_tokens,
                        cost_usd=usage.cost_usd,
                        latency_ms=usage.latency_ms,
                        round=index,
                        ok=entry.accepted,
                        # Only the last round carries the error; the earlier one
                        # returned something, it just wasn't good enough.
                        error=entry.error if index == entry.attempts else None,
                        job_id=job_id,
                        application_id=application_id,
                    )
                )
            if not entry.rounds and entry.error:
                # The call never came back — no tokens, but a dead backend is
                # the single most useful thing this table can tell you.
                db.add(
                    LlmCall(
                        task=entry.task,
                        provider=_configured(entry.task, "provider"),
                        model=_configured(entry.task, "model"),
                        round=1,
                        ok=False,
                        error=entry.error,
                        job_id=job_id,
                        application_id=application_id,
                    )
                )
        return True
    except Exception as exc:
        if linked:
            log.debug("linked llm usage write failed for %s: %s", entry.task, exc)
        else:
            log.warning("could not record llm usage for %s: %s", entry.task, exc)
        return False


def _configured(task: str, what: str) -> str:
    """Provider/model from config, for a call that died before reporting any."""
    try:
        from jobpilot.config import get_config

        cfg = get_config().llm
        return cfg.for_task(task) if what == "provider" else cfg.model_for(task)  # type: ignore[arg-type]
    except Exception:  # pragma: no cover
        return ""
