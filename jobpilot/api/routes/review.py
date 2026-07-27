"""Tailor + CV Review endpoints (PLAN.md §5.6 "CV Review").

Registered **before** ``routes.jobs`` in the app: that router's
``GET /{job_id:path}`` is greedy and would otherwise swallow ``/jobs/x/review``.

Tailoring is synchronous — a Claude call plus a Docker LaTeX build, so tens of
seconds. Fine for a local single-user control plane; Phase 8 moves it behind the
job queue.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from jobpilot.api.deps import get_db, require_token
from jobpilot.api.schemas import JobDetailOut, ReviewOut, TailorIn, TailorOut
from jobpilot.api.ws import manager
from jobpilot.cv.compile import build_dir
from jobpilot.store.models import Job
from jobpilot.tailor import service
from jobpilot.tailor.build import BuildError
from jobpilot.tailor.engine import TailorEngine, TailorError, default_engine
from jobpilot.tailor.guard import GuardrailViolation

router = APIRouter(prefix="/jobs", tags=["review"], dependencies=[Depends(require_token)])


def get_engine() -> TailorEngine:
    """Overridden in tests with a fixture engine (no network, no API key)."""
    return default_engine()


async def _run(
    job_id: str, db: Session, engine: TailorEngine, instruction: str | None
) -> TailorOut:
    try:
        outcome = service.tailor_job(db, job_id, engine, instruction=instruction)
    except service.TailorRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GuardrailViolation as exc:
        # The agent tried to put unsupported claims on the CV — surface it loudly.
        raise HTTPException(status_code=422, detail=f"guardrail: {exc}") from exc
    except (TailorError, BuildError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await manager.broadcast({"type": "job_updated", "id": job_id, "status": "REVIEW"})
    await manager.broadcast(
        {"type": "tailor_done", "id": job_id, "version": outcome.version, "pages": outcome.pages}
    )
    return TailorOut(
        job_id=outcome.job_id,
        version=outcome.version,
        round=outcome.round,
        attempts=outcome.attempts,
        pages=outcome.pages,
        match_score=outcome.plan.match_score,
        plan=outcome.plan.model_dump(mode="json"),
        diff=outcome.diff.model_dump(mode="json"),
    )


@router.post("/{job_id:path}/tailor", response_model=TailorOut)
async def tailor(
    job_id: str,
    db: Session = Depends(get_db),
    engine: TailorEngine = Depends(get_engine),
) -> TailorOut:
    """Tailor the Master CV to this job and build the PDF (SHORTLISTED -> REVIEW)."""
    return await _run(job_id, db, engine, None)


@router.post("/{job_id:path}/edit", response_model=TailorOut)
async def edit(
    job_id: str,
    body: TailorIn,
    db: Session = Depends(get_db),
    engine: TailorEngine = Depends(get_engine),
) -> TailorOut:
    """Re-tailor with a reviewer instruction (SKILL.md §4 edit loop)."""
    if not body.instruction.strip():
        raise HTTPException(status_code=422, detail="instruction must not be empty")
    return await _run(job_id, db, engine, body.instruction.strip())


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
