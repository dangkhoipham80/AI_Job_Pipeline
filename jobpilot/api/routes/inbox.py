"""Employer replies read out of your mailbox (Phase 19).

The sync itself answers 202 with a task, like crawling and applying: it opens an
IMAP connection and then, for the few messages that matched an application,
calls Claude. Neither belongs inside a web request.

Everything else here is small and synchronous, because accepting a suggestion is
a decision you already made — the work was reading the mail, not recording what
you decided about it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from jobpilot.api.deps import get_db, require_token
from jobpilot.api.schemas import ApplicationOut, InboxSettingsOut, SuggestionOut, TaskOut
from jobpilot.api.ws import manager
from jobpilot.apply.inbox import accept_suggestion, dismiss_suggestion, pending_suggestions
from jobpilot.apply.outcome import OutcomeRefused
from jobpilot import llm
from jobpilot.config import get_config
from jobpilot.orchestrator import TaskBusy, inbox_body, queue
from jobpilot.store.models import Job

router = APIRouter(prefix="/inbox", tags=["inbox"], dependencies=[Depends(require_token)])


@router.post("/sync", response_model=TaskOut, status_code=202)
def sync(db: Session = Depends(get_db)) -> JSONResponse:
    """Queue one pass over the mailbox.

    Refuses up front when the channel is off or IMAP isn't configured: that is a
    409 now rather than a task that fails a minute later for a reason the user
    could have been told immediately.
    """
    blocker = get_config().apply.inbox_blocker()
    if blocker:
        raise HTTPException(status_code=409, detail=blocker)
    # A stopped local model is knowable now. Letting it through would spend a
    # mailbox read before failing on the first message it matched.
    model_blocker = llm.blocker("classify")
    if model_blocker:
        raise HTTPException(status_code=409, detail=model_blocker)
    try:
        task = queue.submit("inbox", inbox_body(), label="inbox · reading replies", exclusive=True)
    except TaskBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(status_code=202, content=TaskOut(**task.to_dict()).model_dump(mode="json"))


@router.get("/settings", response_model=InboxSettingsOut)
def settings() -> InboxSettingsOut:
    """What the board shows so a silent sync is never mistaken for "no replies"."""
    cfg = get_config().apply.inbox
    return InboxSettingsOut(
        enabled=cfg.enabled,
        folder=cfg.folder,
        since_days=cfg.since_days,
        blocker=get_config().apply.inbox_blocker(),
    )


@router.get("/suggestions", response_model=list[SuggestionOut])
def list_suggestions(db: Session = Depends(get_db), limit: int = 50) -> list[SuggestionOut]:
    """Replies waiting for your decision, newest mail first."""
    from jobpilot.store.models import Application

    out = []
    for row in pending_suggestions(db, limit=limit):
        app = db.get(Application, row.application_id)
        job = db.get(Job, app.job_id) if app else None
        out.append(SuggestionOut.from_row(row, job))
    return out


@router.post("/suggestions/{suggestion_id}/accept", response_model=ApplicationOut)
async def accept(suggestion_id: int, db: Session = Depends(get_db)) -> ApplicationOut:
    """Yes, that is what happened — write it as a real outcome."""
    try:
        found, app = accept_suggestion(db, suggestion_id)
    except OutcomeRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if found is None or app is None:
        raise HTTPException(status_code=404, detail="suggestion not found")

    await manager.broadcast(
        {
            "type": "outcome_recorded",
            "application_id": app.id,
            "job_id": app.job_id,
            "event_type": found.verdict,
            "label": found.round_label or "",
        }
    )
    return ApplicationOut.from_row(app, db.get(Job, app.job_id))


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=SuggestionOut)
def dismiss(suggestion_id: int, db: Session = Depends(get_db)) -> SuggestionOut:
    """Not what it looked like. The row stays so the sync won't offer it again."""
    from jobpilot.store.models import Application

    found = dismiss_suggestion(db, suggestion_id)
    if found is None:
        raise HTTPException(status_code=404, detail="suggestion not found")
    # Same shape as the list route. Returning a row with an empty job title
    # would give the client a different `SuggestionOut` depending on which
    # endpoint produced it, which is the sort of difference nobody notices
    # until something renders blank.
    app = db.get(Application, found.application_id)
    return SuggestionOut.from_row(found, db.get(Job, app.job_id) if app else None)
