"""Tailor + CV Review endpoints (PLAN.md §5.6 "CV Review").

Registered **before** ``routes.jobs`` in the app: that router's
``GET /{job_id:path}`` is greedy and would otherwise swallow ``/jobs/x/review``.

Tailoring is a Claude call plus a Docker LaTeX build — tens of seconds to a
couple of minutes. It runs on the task queue, so ``POST .../tailor`` answers 202
with a task id and progress arrives over the WebSocket as ``task_updated``.

What is *not* deferred: everything that can be refused by looking at the
database. A job in the wrong state, or an exhausted edit budget, is still an
immediate 409 — queueing a task that was always going to fail would turn a clear
error into a minute of waiting for a bad one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from jobpilot.api.deps import get_db, require_token
from jobpilot.api.schemas import JobDetailOut, ReviewOut, TailorIn, TaskOut
from jobpilot.api.ws import manager
from jobpilot.cv.compile import build_dir
from jobpilot.orchestrator import TaskBusy, queue, tailor_body
from jobpilot.store.models import Job
from jobpilot.tailor import service
from jobpilot.tailor.engine import TailorEngine, default_engine

router = APIRouter(prefix="/jobs", tags=["review"], dependencies=[Depends(require_token)])


def get_engine() -> TailorEngine:
    """Overridden in tests with a fixture engine (no network, no API key)."""
    return default_engine()


def _queue_tailor(
    job_id: str, db: Session, engine: TailorEngine, instruction: str | None
) -> JSONResponse:
    try:
        job, round_no = service.check_tailorable(db, job_id, instruction)
    except service.TailorRefused as exc:
        status = 404 if "not found" in str(exc) else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    label = f"{'edit' if instruction else 'tailor'} · {job.title or job_id}"
    if instruction:
        label += f" (round {round_no})"
    # The engine is resolved here, not in the worker, so a dependency override
    # in tests still reaches the task body.
    try:
        task = queue.submit(
            "tailor",
            tailor_body(job_id, engine, instruction),
            label=label,
            job_id=job_id,
            exclusive=True,
        )
    except TaskBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(status_code=202, content=TaskOut(**task.to_dict()).model_dump(mode="json"))


@router.post("/{job_id:path}/tailor", response_model=TaskOut, status_code=202)
def tailor(
    job_id: str,
    db: Session = Depends(get_db),
    engine: TailorEngine = Depends(get_engine),
) -> JSONResponse:
    """Queue a tailor round for this job (SHORTLISTED -> REVIEW when it lands)."""
    return _queue_tailor(job_id, db, engine, None)


@router.post("/{job_id:path}/edit", response_model=TaskOut, status_code=202)
def edit(
    job_id: str,
    body: TailorIn,
    db: Session = Depends(get_db),
    engine: TailorEngine = Depends(get_engine),
) -> JSONResponse:
    """Queue a re-tailor with a reviewer instruction (SKILL.md §4 edit loop)."""
    if not body.instruction.strip():
        raise HTTPException(status_code=422, detail="instruction must not be empty")
    return _queue_tailor(job_id, db, engine, body.instruction.strip())


@router.get("/{job_id:path}/review", response_model=ReviewOut)
def review(job_id: str, db: Session = Depends(get_db)) -> ReviewOut:
    """Plan, gaps, diff, and version metadata for the review page."""
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    payload = service.review_payload(db, job_id)
    meta = payload["meta"]
    return ReviewOut(
        job_id=job_id,
        version=payload["version"],
        author=payload["author"],
        created_at=payload["created_at"],
        match_score=meta.get("match_score"),
        pages=meta.get("pages"),
        round=meta.get("round", 0),
        instruction=meta.get("instruction"),
        plan=meta.get("plan"),
        diff=meta.get("diff"),
        gaps=meta.get("gaps", []),
    )


@router.get("/{job_id:path}/cv")
def tailored_pdf(job_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """The tailored PDF for this job, as last compiled."""
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    pdf = build_dir(job_id) / "cv.pdf"
    if not pdf.is_file():
        raise HTTPException(status_code=404, detail="not tailored yet")
    return FileResponse(pdf, media_type="application/pdf", filename=f"cv-{job_id}.pdf")


@router.post("/{job_id:path}/approve", response_model=JobDetailOut)
async def approve(job_id: str, db: Session = Depends(get_db)) -> JobDetailOut:
    """REVIEW -> APPROVED. Nothing is sent anywhere yet — that is Phase 6."""
    return await _decide(job_id, db, service.approve)


@router.post("/{job_id:path}/reject", response_model=JobDetailOut)
async def reject(job_id: str, db: Session = Depends(get_db)) -> JobDetailOut:
    """Drop the job after review; tailored versions are kept for the record."""
    return await _decide(job_id, db, service.reject)


async def _decide(job_id: str, db: Session, action) -> JobDetailOut:
    try:
        job = action(db, job_id)
    except service.TailorRefused as exc:
        status = 404 if "not found" in str(exc) else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    await manager.broadcast({"type": "job_updated", "id": job.id, "status": job.status.value})
    return JobDetailOut.from_job(job)
