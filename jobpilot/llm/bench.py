"""Measuring a backend against a known answer, instead of arguing about it.

Phase 20 compared two backends by driving five emails with known labels and four
real jobs, then writing the result into a document. The numbers were good; the
method was a person doing it once. This is the same method as a command, so the
next backend can be judged the same way rather than on how it feels.

Two benchmarks, because the two calls fail differently:

* **classify** has a right answer, so it is scored against one. The fixtures
  below are fictional employer mail — no real correspondence, for the same
  reason ``cv/sample.py`` is a made-up CV.
* **tailor** has no single right answer; a plan can be good or bad without being
  wrong. What it has is a *floor*: the guardrails. So it is scored on how often
  the model clears the floor, and on whether it needs the corrective round to do
  it. Phase 20's local 7B scored 0/4 here — not on truthfulness, but on
  navigating the schema.

Neither writes anything. Bench runs cost money on a paid backend and produce
nothing but a number, which is the point.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jobpilot.crawler.mailbox import MailMessage

# --------------------------------------------------------------------------- #
# classify: five messages with known labels
# --------------------------------------------------------------------------- #
#: (message, expected verdict). Chosen to cover the distinctions that actually
#: get confused: an automated receipt is *not* a reply, and a rejection that
#: opens politely is still a rejection.
CLASSIFY_FIXTURES: list[tuple[MailMessage, str]] = [
    (
        MailMessage(
            uid="bench-1",
            subject="We received your application",
            sender="no-reply@acme-careers.example",
            date=None,
            html="",
            text=(
                "Thank you for applying to ACME. This is an automated confirmation "
                "that your application has been received. Please do not reply to "
                "this message."
            ),
        ),
        "auto_ack",
    ),
    (
        MailMessage(
            uid="bench-2",
            subject="Re: Backend Engineer application",
            sender="linh@acme.example",
            date=None,
            html="",
            text=(
                "Hi, thanks for getting in touch. I have passed your CV to the "
                "hiring manager and will come back to you next week."
            ),
        ),
        "replied",
    ),
    (
        MailMessage(
            uid="bench-3",
            subject="Technical interview — scheduling",
            sender="talent@acme.example",
            date=None,
            html="",
            text=(
                "We would like to invite you to a 60-minute technical interview. "
                "Are you available on Tuesday or Thursday afternoon?"
            ),
        ),
        "interview",
    ),
    (
        MailMessage(
            uid="bench-4",
            subject="Your application to ACME",
            sender="talent@acme.example",
            date=None,
            html="",
            text=(
                "Thank you for the time you spent with us. After careful "
                "consideration we have decided to move forward with another "
                "candidate for this position. We wish you the best."
            ),
        ),
        "rejected",
    ),
    (
        MailMessage(
            uid="bench-5",
            subject="Offer of employment — Backend Engineer",
            sender="hr@acme.example",
            date=None,
            html="",
            text=(
                "We are delighted to offer you the position of Backend Engineer. "
                "The formal offer letter is attached for your review."
            ),
        ),
        "offer",
    ),
]


@dataclass
class BenchResult:
    task: str
    provider: str
    model: str
    total: int = 0
    correct: int = 0
    #: Only meaningful for tailor: accepted without a corrective round.
    first_try: int = 0
    failed: int = 0
    notes: list[str] = field(default_factory=list)


def resolve(task: str, provider: str = "", model: str = ""):
    """The client to benchmark: the configured one, or an explicit override.

    Overrides exist so that sweeping candidate models is a loop rather than a
    sequence of config edits. "Which is the cheapest model that still works" is
    a question with a numeric answer, and asking it should not cost a commit.
    """
    from jobpilot.config import get_config
    from jobpilot.llm.registry import api_key, provider_for

    cfg = get_config().llm
    name = provider or cfg.for_task(task)  # type: ignore[arg-type]
    entry = provider_for(name)
    chosen = model or (cfg.model_for(task) if not provider else entry.default_model)  # type: ignore[arg-type]
    return entry.build(chosen, api_key(name), task), name


def bench_classify(limit: int = 0, provider: str = "", model: str = "") -> BenchResult:
    """Score a classifier against the fixtures above."""
    from jobpilot.apply.inbox import Applied, ModelClassifier, check_verdict
    from jobpilot.tailor.engine import TailorError

    client, name = resolve("classify", provider, model)
    result = BenchResult(task="classify", provider=name, model=client.model)
    engine = ModelClassifier(client)
    app = Applied(0, "bench:1", "ACME", "Backend Engineer")

    cases = CLASSIFY_FIXTURES[: limit or len(CLASSIFY_FIXTURES)]
    for mail, expected in cases:
        result.total += 1
        try:
            verdict = engine.classify(mail, app)
        except TailorError as exc:
            result.failed += 1
            result.notes.append(f"{mail.uid}: call failed - {exc}")
            continue
        if verdict.verdict == expected:
            result.correct += 1
        else:
            result.notes.append(f"{mail.uid}: expected {expected}, got {verdict.verdict}")
        # The quote guard runs outside the engine in production, so it runs here
        # too — a right label with an invented quote is dropped in real use and
        # should not score as a win.
        problems = check_verdict(verdict, mail)
        if problems:
            result.notes.append(f"{mail.uid}: verdict would be dropped - {'; '.join(problems)}")
    return result


def bench_tailor(db, limit: int = 4, provider: str = "", model: str = "") -> BenchResult:
    """Run the configured tailor over real jobs and score it on the guardrails.

    Real jobs and the real Master CV, because a benchmark on fixtures measures
    the fixtures. Nothing is written: no version row, no PDF.
    """
    from sqlalchemy import select

    from jobpilot.cv.store import MASTER_SCOPE, get_document
    from jobpilot.store.models import Job
    from jobpilot.tailor.engine import ModelTailorEngine, TailorError
    from jobpilot.tailor.guard import GuardrailViolation

    client, name = resolve("tailor", provider, model)
    result = BenchResult(task="tailor", provider=name, model=client.model)

    master = get_document(db, MASTER_SCOPE)
    jobs = [
        job
        for job in db.execute(select(Job).order_by(Job.crawled_at.desc()).limit(limit * 5))
        .scalars()
        .all()
        if (job.payload or {}).get("description_md")
    ][:limit]

    if not jobs:
        result.notes.append("no crawled jobs with a description - run a crawl first")
        return result

    engine = ModelTailorEngine(client)
    for job in jobs:
        result.total += 1
        try:
            outcome = engine.tailor(master, job)
        except GuardrailViolation as exc:
            result.failed += 1
            result.notes.append(f"{job.id}: guardrail - {exc}")
            continue
        except TailorError as exc:
            result.failed += 1
            result.notes.append(f"{job.id}: call failed - {exc}")
            continue
        result.correct += 1
        if outcome.attempts == 1:
            result.first_try += 1
        else:
            result.notes.append(f"{job.id}: needed a retry - {'; '.join(outcome.retried_for)}")
    return result
