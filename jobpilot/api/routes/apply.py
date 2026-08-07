"""Apply dispatch + the Applications board (PLAN.md §5.4, §5.6).

Like ``routes.review``, the ``/jobs/...`` routes here must be registered before
``routes.jobs`` — its ``GET /{job_id:path}`` is greedy.

Applying writes a cover letter with Claude and may talk to an SMTP server, so it
runs on the task queue like tailoring: ``POST .../apply`` answers 202 with a task
id. What the dispatch actually *did* lands in ``task.result`` — ``dry_run`` means
nothing left the machine, ``awaiting_user`` means the human still has to submit.
Collapsing those into "200/OK" would be the one lie this module can't afford.

Bad state is still refused synchronously: a job that was never tailored has no
PDF to attach, and that should be a 409 now, not a task failure later.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from jobpilot.api.deps import get_db, require_token
from jobpilot.api.schemas import (
    ApplicationEventOut,
    ApplicationOut,
    ApplyIn,
    FailureIn,
    JobDetailOut,
    OutcomeIn,
    TaskOut,
)
from jobpilot.api.ws import manager
from jobpilot.apply import dispatcher
from jobpilot.apply.followup import due_applications, mark_followed_up, stop_followups
from jobpilot.apply.outcome import (
    OutcomeRefused,
    list_outcome_events,
    record_outcome,
    retract_outcome_event,
)
from jobpilot.apply.letter import LetterEngine, default_letter_engine
from jobpilot.config import get_config, get_secrets
from jobpilot.orchestrator import TaskBusy, apply_body, queue
from jobpilot.store.models import Application, Job

router = APIRouter(prefix="/jobs", tags=["apply"], dependencies=[Depends(require_token)])
board = APIRouter(prefix="/applications", tags=["apply"], dependencies=[Depends(require_token)])


def get_letter_engine() -> LetterEngine | None:
    """None when no Claude key is configured — apply still works, just without a
    cover letter, which beats blocking a portal handoff on an unrelated key."""
    return default_letter_engine() if get_secrets().anthropic_api_key else None


@router.post("/{job_id:path}/apply", response_model=TaskOut, status_code=202)
def apply(
    job_id: str,
    body: ApplyIn | None = None,
    db: Session = Depends(get_db),
    engine: LetterEngine | None = Depends(get_letter_engine),
) -> JSONResponse:
    """Queue a dispatch to this job's channel. Email may send for real — see the
    gates in ``apply.email``; portal/external only ever prepare a handoff."""
    wants_letter = True if body is None or body.cover_letter is None else body.cover_letter
    try:
        job, _cv_pdf = dispatcher.check_appliable(db, job_id)
    except dispatcher.ApplyRefused as exc:
        status = 404 if "not found" in str(exc) else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    try:
        task = queue.submit(
            "apply",
            apply_body(job_id, engine if wants_letter else None),
            label=f"apply · {job.title or job_id}",
            job_id=job_id,
            exclusive=True,
        )
    except TaskBusy as exc:
        # Including a tailor round still in flight: applying the CV it is midway
        # through rewriting would attach whichever version won the race.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(status_code=202, content=TaskOut(**task.to_dict()).model_dump(mode="json"))


@router.post("/{job_id:path}/confirm-submit", response_model=JobDetailOut)
async def confirm_submit(job_id: str, db: Session = Depends(get_db)) -> JobDetailOut:
    """The user submitted a portal/external application by hand."""
    return await _decide(job_id, db, lambda: dispatcher.confirm_submit(db, job_id))


@router.post("/{job_id:path}/report-failure", response_model=JobDetailOut)
async def report_failure(
    job_id: str, body: FailureIn, db: Session = Depends(get_db)
) -> JobDetailOut:
    """The user reports the submission didn't go through."""
    reason = body.reason.strip() or "reported failed by the user"
    return await _decide(job_id, db, lambda: dispatcher.mark_failed(db, job_id, reason))


async def _decide(job_id: str, db: Session, action) -> JobDetailOut:
    try:
        job = action()
    except dispatcher.ApplyRefused as exc:
        status = 404 if "not found" in str(exc) else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    await manager.broadcast({"type": "job_updated", "id": job.id, "status": job.status.value})
    return JobDetailOut.from_job(job)


@board.get("", response_model=list[ApplicationOut])
def list_applications(
    db: Session = Depends(get_db),
    result: str | None = None,
    limit: int = 200,
) -> list[ApplicationOut]:
    """Rows for the Applications board, newest first."""
    query = db.query(Application, Job).join(Job, Application.job_id == Job.id)
    if result:
        query = query.filter(Application.result == result)
    rows = query.order_by(Application.id.desc()).limit(limit).all()
    return [ApplicationOut.from_row(app, job) for app, job in rows]


@board.get("/followups", response_model=list[ApplicationOut])
def list_followups(db: Session = Depends(get_db), limit: int = 50) -> list[ApplicationOut]:
    """Applications whose next follow-up has come due, oldest first.

    Read-only on purpose. Nothing is sent from here: a follow-up is a message to
    a person deciding about you, and mail that leaves the machine without you
    seeing it is exactly what principle 2 forbids.
    """
    rows = []
    for app in due_applications(db, limit=limit):
        job = db.get(Job, app.job_id)
        if job is not None:
            rows.append(ApplicationOut.from_row(app, job))
    return rows


@board.post("/{application_id}/followed-up", response_model=ApplicationOut)
def followed_up(application_id: int, db: Session = Depends(get_db)) -> ApplicationOut:
    """You sent the nudge — advance the cadence (or end it)."""
    app = mark_followed_up(db, application_id)
    if app is None:
        raise HTTPException(status_code=404, detail="application not found")
    return ApplicationOut.from_row(app, db.get(Job, app.job_id))


@board.post("/{application_id}/stop-followups", response_model=ApplicationOut)
def stop_followup(application_id: int, db: Session = Depends(get_db)) -> ApplicationOut:
    """Let one go — after a reply, a rejection, or a change of heart."""
    app = stop_followups(db, application_id)
    if app is None:
        raise HTTPException(status_code=404, detail="application not found")
    return ApplicationOut.from_row(app, db.get(Job, app.job_id))


@board.post("/{application_id}/outcome", response_model=ApplicationOut)
async def add_outcome(
    application_id: int, body: OutcomeIn, db: Session = Depends(get_db)
) -> ApplicationOut:
    """Record what happened after this one went out (Phase 18).

    Synchronous on purpose: this is a fact the user already knows, not work the
    machine has to go and do, so a 202 and a task id would be ceremony.
    """
    try:
        event, app = record_outcome(
            db,
            application_id,
            body.event_type,
            occurred_at=body.occurred_at,
            label=body.label,
            notes=body.notes,
        )
    except OutcomeRefused as exc:
        # Nothing left the machine, so nobody could have answered. A 409 rather
        # than a quiet write: the number this would corrupt is the one the
        # dashboard divides by.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if app is None:
        raise HTTPException(status_code=404, detail="application not found")

    await manager.broadcast(
        {
            "type": "outcome_recorded",
            "application_id": app.id,
            "job_id": app.job_id,
            "event_type": event.event_type,
            "label": event.label or "",
        }
    )
    return ApplicationOut.from_row(app, db.get(Job, app.job_id))


@board.get("/{application_id}/events", response_model=list[ApplicationEventOut])
def list_events(application_id: int, db: Session = Depends(get_db)) -> list[ApplicationEventOut]:
    """This application's history, oldest first, retracted entries included.

    404s on an unknown application rather than returning ``[]``: "no history" and
    "no such application" are different answers and the UI treats them differently.
    """
    if db.get(Application, application_id) is None:
        raise HTTPException(status_code=404, detail="application not found")
    return [ApplicationEventOut.model_validate(e) for e in list_outcome_events(db, application_id)]


@board.delete("/{application_id}/events/{event_id}", response_model=ApplicationOut)
def retract_event(
    application_id: int, event_id: int, db: Session = Depends(get_db)
) -> ApplicationOut:
    """Undo a mis-click. The row stays; the stage rewinds to the previous one."""
    app = retract_outcome_event(db, application_id, event_id)
    if app is None:
        raise HTTPException(status_code=404, detail="event not found")
    return ApplicationOut.from_row(app, db.get(Job, app.job_id))


@board.get("/settings")
def apply_settings() -> dict:
    """Which gates are currently open — the board shows this so a dry run is
    never mistaken for a real send."""
    cfg = get_config().apply
    return {
        "email_enabled": cfg.email.enabled,
        "email_dry_run": cfg.email.dry_run,
        "email_test_recipient": cfg.email.test_recipient,
        "email_from": cfg.email.from_addr,
        "email_blocker": cfg.email_blocker(),
        "portal_prefill": cfg.portal_prefill,
    }
