"""Apply dispatch + the Applications board (PLAN.md §5.4, §5.6).

Like ``routes.review``, the ``/jobs/...`` routes here must be registered before
``routes.jobs`` — its ``GET /{job_id:path}`` is greedy.

Applying can send real mail, so the endpoint reports exactly what happened
(``result``) rather than collapsing everything into 200/OK: ``dry_run`` means
nothing left the machine, ``awaiting_user`` means the human still has to submit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from jobpilot.api.deps import get_db, require_token
from jobpilot.api.schemas import ApplicationOut, ApplyIn, ApplyOut, FailureIn, JobDetailOut
from jobpilot.api.ws import manager
from jobpilot.apply import dispatcher
from jobpilot.apply.letter import LetterEngine, default_letter_engine
from jobpilot.config import get_config, get_secrets
from jobpilot.store.models import Application, Job

router = APIRouter(prefix="/jobs", tags=["apply"], dependencies=[Depends(require_token)])
board = APIRouter(prefix="/applications", tags=["apply"], dependencies=[Depends(require_token)])


def get_letter_engine() -> LetterEngine | None:
    """None when no Claude key is configured — apply still works, just without a
    cover letter, which beats blocking a portal handoff on an unrelated key."""
    return default_letter_engine() if get_secrets().anthropic_api_key else None


@router.post("/{job_id:path}/apply", response_model=ApplyOut)
async def apply(
    job_id: str,
    body: ApplyIn | None = None,
    db: Session = Depends(get_db),
    engine: LetterEngine | None = Depends(get_letter_engine),
) -> ApplyOut:
    """Dispatch this job to its channel. Email may send for real — see the gates
    in ``apply.email``; portal/external only ever prepare a handoff."""
    wants_letter = True if body is None or body.cover_letter is None else body.cover_letter
    try:
        outcome = dispatcher.apply_job(db, job_id, engine if wants_letter else None)
    except dispatcher.ApplyRefused as exc:
        status = 404 if "not found" in str(exc) else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    job = db.get(Job, job_id)
    await manager.broadcast(
        {"type": "job_updated", "id": job_id, "status": job.status.value if job else None}
    )
    await manager.broadcast(
        {"type": "apply_done", "id": job_id, "channel": outcome.channel, "result": outcome.result}
    )
    return ApplyOut(
        job_id=outcome.job_id,
        channel=outcome.channel,
        result=outcome.result,
        detail=outcome.detail,
        application_id=outcome.application_id,
        email=outcome.email.summary() if outcome.email else None,
        handoff=outcome.handoff.summary() if outcome.handoff else None,
    )


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
