"""Orchestrates one tailor round for a job (PLAN.md §4 state machine).

    SHORTLISTED ─tailor─▶ TAILORING ─┬─ok────▶ REVIEW ─approve─▶ APPROVED
                                     └─fail──▶ FAILED            └─skip───▶ SKIPPED

Each round appends a ``cv_versions`` row scoped to the job with ``author='agent'``
and the plan in ``meta``, so the tailored CV, the reasoning behind it, and the
diff the reviewer saw are one immutable record. Re-running is safe: it appends a
new version rather than overwriting the last one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobpilot.config import get_config
from jobpilot.cv import store as cv_store
from jobpilot.cv.compile import compile_document
from jobpilot.store.models import Edit, Job, JobStatus, Run
from jobpilot.tailor.apply import apply_plan
from jobpilot.tailor.build import BuildError
from jobpilot.tailor.diff import CvDiff, diff_documents
from jobpilot.tailor.engine import TailorEngine, TailorError
from jobpilot.tailor.guard import GuardrailViolation
from jobpilot.tailor.schema import TailorPlan
from jobpilot.timeutil import vn_now

# Statuses a tailor round may start from. FAILED is included so a build or API
# hiccup doesn't strand the job.
TAILORABLE = {JobStatus.SHORTLISTED, JobStatus.REVIEW, JobStatus.FAILED, JobStatus.TAILORING}


class TailorRefused(RuntimeError):
    """The job is not in a state where this action makes sense."""


@dataclass
class TailorOutcome:
    job_id: str
    version: int
    plan: TailorPlan
    diff: CvDiff
    pages: int | None = None
    attempts: int = 1
    round: int = 1


def latest_meta(db: Session, job_id: str) -> dict:
    """Tailor meta of the newest version for this job ({} if none/hand-edited)."""
    row = cv_store.latest_version(db, job_id)
    return (row.meta or {}) if row else {}


def latest_plan(db: Session, job_id: str) -> TailorPlan | None:
    """The plan behind the newest agent version — the base for an edit round."""
    for row in cv_store.list_versions(db, job_id):
        plan = (row.meta or {}).get("plan")
        if plan:
            return TailorPlan.model_validate(plan)
    return None


def _finish_run(db: Session, run: Run, stats: dict) -> None:
    run.finished_at = vn_now()
    run.stats = stats
    db.add(run)


def check_tailorable(db: Session, job_id: str, instruction: str | None = None) -> tuple[Job, int]:
    """Everything that can be refused before any slow work starts.

    Split out so the API can answer "this job is DISCOVERED" or "you've used
    your edit rounds" with a 409 in the request, instead of queueing a task
    that was always going to fail. ``tailor_job`` calls it too, because the
    state can move between queueing and running.

    Returns the job and the round number this attempt would be.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise TailorRefused(f"job {job_id!r} not found")
    if job.status not in TAILORABLE:
        raise TailorRefused(
            f"job {job_id!r} is {job.status.value}; tailoring starts from "
            + "/".join(sorted(s.value for s in TAILORABLE))
        )
    if not instruction:
        return job, 1

    cfg = get_config()
    used = db.scalar(select(func.count()).select_from(Edit).where(Edit.job_id == job_id)) or 0
    if used >= cfg.app.edit_max_rounds:
        raise TailorRefused(
            f"edit limit reached ({cfg.app.edit_max_rounds} rounds) — approve or skip this job"
        )
    return job, used + 1


def tailor_job(
    db: Session,
    job_id: str,
    engine: TailorEngine,
    instruction: str | None = None,
    compile_pdf: bool = True,
    progress: Callable[[str], None] | None = None,
) -> TailorOutcome:
    """Run one tailor round. Raises ``TailorRefused``/``TailorError``/``BuildError``.

    ``progress`` reports the stage the round is in. It matters more than a
    spinner would: the Claude call and the LaTeX build fail for entirely
    different reasons, and the user should be able to see which one is running.
    """
    say = progress or (lambda _message: None)
    job, round_no = check_tailorable(db, job_id, instruction)

    master = cv_store.get_document(db, cv_store.MASTER_SCOPE)
    previous = latest_plan(db, job_id) if instruction else None

    run = Run(kind="tailor", started_at=vn_now())
    db.add(run)
    job.status = JobStatus.TAILORING
    db.commit()

    try:
        say("re-planning with your instruction" if instruction else "planning against the JD")
        result = engine.tailor(master, job, instruction=instruction, previous=previous)
        tailored = apply_plan(master, result.plan)
    except (TailorError, GuardrailViolation) as exc:
        job.status = JobStatus.FAILED
        _finish_run(db, run, {"job_id": job_id, "ok": False, "error": str(exc)})
        db.commit()
        raise

    diff = diff_documents(master, tailored)
    pages: int | None = None
    if compile_pdf:
        try:
            say("building the PDF")
            pages = compile_document(tailored, job_id).pages
        except BuildError as exc:
            job.status = JobStatus.FAILED
            _finish_run(db, run, {"job_id": job_id, "ok": False, "error": f"build: {exc}"})
            db.commit()
            raise

    meta = _build_meta(result.plan, diff, pages, result.attempts, round_no, instruction)
    version = cv_store.save_version(db, job_id, tailored, author="agent", meta=meta, commit=False)

    if instruction:
        db.add(Edit(job_id=job_id, round=round_no, instruction=instruction))
    job.status = JobStatus.REVIEW
    job.match_score = result.plan.match_score
    _finish_run(
        db,
        run,
        {
            "job_id": job_id,
            "ok": True,
            "match_score": result.plan.match_score,
            "gaps": len(result.plan.gaps()),
            "pages": pages,
            "attempts": result.attempts,
            "round": round_no,
        },
    )
    db.commit()

    return TailorOutcome(
        job_id=job_id,
        version=version.version,
        plan=result.plan,
        diff=diff,
        pages=pages,
        attempts=result.attempts,
        round=round_no,
    )


def _build_meta(
    plan: TailorPlan,
    diff: CvDiff,
    pages: int | None,
    attempts: int,
    round_no: int,
    instruction: str | None,
) -> dict:
    return {
        "plan": plan.model_dump(mode="json"),
        "diff": diff.model_dump(mode="json"),
        "match_score": plan.match_score,
        "gaps": [g.model_dump(mode="json") for g in plan.gaps()],
        "keywords": plan.keywords(),
        "pages": pages,
        "attempts": attempts,
        "round": round_no,
        "instruction": instruction,
    }


def approve(db: Session, job_id: str) -> Job:
    """REVIEW -> APPROVED. The CV is now the one that gets sent."""
    return _transition(db, job_id, {JobStatus.REVIEW}, JobStatus.APPROVED)


def reject(db: Session, job_id: str) -> Job:
    """Drop the job from the funnel; the tailored versions stay for the record."""
    return _transition(
        db, job_id, {JobStatus.REVIEW, JobStatus.TAILORING, JobStatus.FAILED}, JobStatus.SKIPPED
    )


def _transition(db: Session, job_id: str, allowed: set[JobStatus], target: JobStatus) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise TailorRefused(f"job {job_id!r} not found")
    if job.status not in allowed:
        raise TailorRefused(
            f"job {job_id!r} is {job.status.value}; expected "
            + "/".join(sorted(s.value for s in allowed))
        )
    job.status = target
    db.commit()
    return job


def review_payload(db: Session, job_id: str) -> dict:
    """Everything the CV Review page needs for one job."""
    row = cv_store.latest_version(db, job_id)
    if row is None:
        return {"job_id": job_id, "version": 0, "meta": {}, "author": None, "created_at": None}
    created: datetime | None = row.created_at
    return {
        "job_id": job_id,
        "version": row.version,
        "author": row.author,
        "created_at": created,
        "meta": row.meta or {},
    }
