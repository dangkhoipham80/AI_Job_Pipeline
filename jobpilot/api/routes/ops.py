"""Operations surface: trigger crawls, watch tasks, read run history, edit settings.

Crawling is the one action that genuinely cannot answer inside a request — it
walks several sites behind a rate limiter. So ``POST /crawl`` returns 202 with a
task id, and progress arrives over the existing WebSocket as ``task_updated``.

Settings writes go to a gitignored overlay (``config.local.yaml``) rather than
editing ``config.yaml``, whose comments document the email safety gates.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobpilot.api.deps import get_db, require_token
from jobpilot.api.schemas import RunOut, SettingsIn, TaskOut
from jobpilot.config import get_config, save_local_config
from jobpilot.orchestrator import crawl_body, queue
from jobpilot.store.models import Job, Run

router = APIRouter(tags=["ops"], dependencies=[Depends(require_token)])


@router.post("/crawl", response_model=TaskOut, status_code=202)
def start_crawl(
    query: str | None = None,
    no_robots: bool = False,
) -> JSONResponse:
    """Queue a crawl. Returns immediately; watch the task for progress.

    Only one crawl at a time — a second would race the same sites and trip
    their rate limits.
    """
    running = queue.active(kind="crawl")
    if running:
        raise HTTPException(
            status_code=409, detail=f"a crawl is already {running[0].status} ({running[0].id})"
        )
    task = queue.submit(
        "crawl",
        crawl_body(query=query, respect_robots=not no_robots),
        label=f"crawl {query}" if query else "crawl",
    )
    return JSONResponse(status_code=202, content=TaskOut(**task.to_dict()).model_dump(mode="json"))


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(kind: str | None = None, limit: int = Query(50, ge=1, le=200)) -> list[TaskOut]:
    return [TaskOut(**t.to_dict()) for t in queue.list(limit=limit, kind=kind)]


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str) -> TaskOut:
    task = queue.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found (the queue keeps the last 50)")
    return TaskOut(**task.to_dict())


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[RunOut]:
    """Persisted history of crawl/tailor/apply runs, newest first."""
    stmt = select(Run)
    if kind:
        stmt = stmt.where(Run.kind == kind)
    rows = list(db.scalars(stmt.order_by(Run.id.desc()).limit(limit)))

    counts = dict(
        db.execute(
            select(Job.run_id, func.count())
            .where(Job.run_id.in_([r.id for r in rows]))
            .group_by(Job.run_id)
        ).all()
    )
    out = []
    for row in rows:
        item = RunOut.model_validate(row)
        item.job_count = counts.get(row.id, 0)
        out.append(item)
    return out


@router.get("/settings")
def read_settings() -> dict:
    """The resolved config (base + overlay). Secrets are never included."""
    return get_config().model_dump()


@router.put("/settings")
def write_settings(body: SettingsIn) -> dict:
    """Patch the overlay. Rejected as a whole if the result wouldn't validate."""
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=422, detail="nothing to change")
    try:
        return save_local_config(patch).model_dump()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid settings: {exc}") from exc
