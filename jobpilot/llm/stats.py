"""Reading ``llm_calls`` back as an answer to "which backend should run this".

Four numbers per (task, provider, model), because four different things can make
a backend the wrong choice and only one of them is price:

* **cost** — what it actually billed, summed from real calls rather than guessed
  from a rate card.
* **first-try rate** — the share of tasks the guardrails accepted without a
  corrective round. This is the quality number. Phase 20 measured it by hand on
  four jobs; this is the same measurement, continuous.
* **success rate** — the share that produced a usable answer at all.
* **latency** — p50 and p95. The queue runs one worker, so a slow backend does
  not just cost time on its own task, it holds up everything behind it.

**Small samples report counts, not rates.** Three calls with two failures is not
"33% success"; it is three calls. Percentages invite comparison, and comparing
two backends on three calls each is how a coin flip becomes a decision. Below
``MIN_SAMPLE`` the rates come back ``None`` and the caller shows the raw counts —
the same rule ``outcome_counts`` follows, and for the same reason.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

#: Below this many completed tasks, rates are withheld rather than rounded.
#: Ten is not a statistical threshold — it is the point where a single outlier
#: stops moving the number by more than a tenth.
MIN_SAMPLE = 10


@dataclass
class BackendStats:
    task: str
    provider: str
    model: str
    #: Distinct tasks, not rounds. A tailor that retried once is one attempt.
    attempts: int
    rounds: int
    #: None when no round on record carried a price — see ``pricing.estimate_cost``.
    cost_usd: float | None
    #: How many rounds had no price. A total built from half the rows is a
    #: number that will be read as if it were built from all of them.
    unpriced_rounds: int
    input_tokens: int
    output_tokens: int
    p50_latency_ms: int
    p95_latency_ms: int
    #: None below MIN_SAMPLE.
    first_try_rate: float | None
    success_rate: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def backend_stats(db, *, task: str | None = None) -> list[dict]:
    """One row per (task, provider, model), busiest first."""
    from sqlalchemy import select

    from jobpilot.store.models import LlmCall

    query = select(
        LlmCall.task,
        LlmCall.provider,
        LlmCall.model,
        LlmCall.round,
        LlmCall.ok,
        LlmCall.cost_usd,
        LlmCall.input_tokens,
        LlmCall.output_tokens,
        LlmCall.latency_ms,
    )
    if task:
        query = query.where(LlmCall.task == task)

    buckets: dict[tuple[str, str, str], dict] = {}
    for row in db.execute(query).all():
        key = (row.task, row.provider, row.model)
        acc = buckets.setdefault(
            key,
            {
                "rounds": 0,
                "attempts": 0,
                "first_try": 0,
                "succeeded": 0,
                "cost": 0.0,
                "unpriced": 0,
                "input": 0,
                "output": 0,
                "latencies": [],
            },
        )
        acc["rounds"] += 1
        acc["input"] += row.input_tokens or 0
        acc["output"] += row.output_tokens or 0
        if row.latency_ms:
            acc["latencies"].append(row.latency_ms)
        if row.cost_usd is None:
            acc["unpriced"] += 1
        else:
            acc["cost"] += row.cost_usd
        # Round 1 is the one row per task that always exists, so counting
        # attempts there avoids double-counting a task that retried.
        if row.round == 1:
            acc["attempts"] += 1
            if row.ok:
                acc["succeeded"] += 1

    # A task that succeeded on round 1 has no round-2 row, so "accepted first
    # try" is "succeeded and never came back for a second round" — the successes
    # minus the successes that needed a retry.
    #
    # Both halves of that subtraction have to be counting the same population.
    # A task that retried and *still* failed contributes a round-2 row but was
    # never in `succeeded`, so subtracting it takes away a first-try success
    # that has nothing to do with it. Hence `successful_only`.
    retries = _retry_counts(db, task)
    out: list[BackendStats] = []
    for key, acc in buckets.items():
        attempts = acc["attempts"]
        enough = attempts >= MIN_SAMPLE
        first_try = max(acc["succeeded"] - retries.get(key, 0), 0)
        out.append(
            BackendStats(
                task=key[0],
                provider=key[1],
                model=key[2],
                attempts=attempts,
                rounds=acc["rounds"],
                cost_usd=None if acc["unpriced"] == acc["rounds"] else round(acc["cost"], 6),
                unpriced_rounds=acc["unpriced"],
                input_tokens=acc["input"],
                output_tokens=acc["output"],
                p50_latency_ms=_percentile(acc["latencies"], 0.50),
                p95_latency_ms=_percentile(acc["latencies"], 0.95),
                first_try_rate=(first_try / attempts) if enough and attempts else None,
                success_rate=(acc["succeeded"] / attempts) if enough and attempts else None,
            )
        )
    out.sort(key=lambda s: (-s.attempts, s.task, s.provider, s.model))
    return [s.to_dict() for s in out]


def _retry_counts(db, task: str | None) -> dict[tuple[str, str, str], int]:
    """How many *successful* tasks needed a second round, per backend.

    Successful only, because this number is subtracted from the success count.
    Counting every retry would let a task that retried and failed cancel out an
    unrelated task that got it right first time — reporting a backend as worse
    at first-try accuracy than it is, which is the wrong direction to be wrong
    in the one table built for choosing between backends.
    """
    from sqlalchemy import func, select

    from jobpilot.store.models import LlmCall

    query = (
        select(LlmCall.task, LlmCall.provider, LlmCall.model, func.count())
        .where(LlmCall.round > 1)
        .where(LlmCall.ok.is_(True))
        .group_by(LlmCall.task, LlmCall.provider, LlmCall.model)
    )
    if task:
        query = query.where(LlmCall.task == task)
    return {(t, p, m): n for t, p, m, n in db.execute(query).all()}


def _percentile(values: list[int], fraction: float) -> int:
    """Nearest-rank percentile. 0 for an empty list, which reads as "no data"
    everywhere it is displayed — latency is never legitimately zero."""
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * len(ordered) + 0.5) - 1))
    return ordered[index]
