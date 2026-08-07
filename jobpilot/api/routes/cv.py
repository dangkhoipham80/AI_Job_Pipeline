"""CV Studio endpoints: read/save the structured document, compile it, browse versions.

``scope`` is ``master`` for the Master CV or a job id for a tailored one. Job ids
contain ``:`` (e.g. ``itviec:abc``), which is legal in a path segment; clients
should still ``encodeURIComponent`` it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from jobpilot.api.deps import get_db, require_token
from jobpilot.api.schemas import (
    CvCompileOut,
    CvDocumentOut,
    CvVersionDetailOut,
    CvVersionDiffOut,
    CvVersionOut,
)
from jobpilot.api.ws import manager
from jobpilot.cv import store
from jobpilot.cv.compile import build_dir, check_build, compile_document
from jobpilot.cv.render import list_templates, render_tex_snapshot
from jobpilot.cv.schema import CvDocument
from jobpilot.store.models import Job
from jobpilot.tailor.build import BuildError
from jobpilot.tailor.diff import VERSION_LABELS, diff_documents

router = APIRouter(prefix="/cv", tags=["cv"], dependencies=[Depends(require_token)])


def _load(db: Session, scope: str) -> CvDocument:
    try:
        return store.get_document(db, scope)
    except store.ScopeNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# Static path first so it isn't swallowed by /{scope}.
@router.get("/templates")
def templates() -> dict:
    return {"templates": list_templates()}


@router.get("/{scope}", response_model=CvDocumentOut)
def get_cv(scope: str, db: Session = Depends(get_db)) -> CvDocumentOut:
    """Current document for the scope. Auto-seeds ``master`` from the imported CV."""
    doc = _load(db, scope)
    row = store.latest_version(db, scope)
    return CvDocumentOut(scope=scope, version=row.version if row else 0, document=doc)


@router.put("/{scope}", response_model=CvDocumentOut)
async def put_cv(
    scope: str,
    document: CvDocument,
    author: str = "user",
    db: Session = Depends(get_db),
) -> CvDocumentOut:
    """Save a new version. Every save appends -- nothing is overwritten."""
    if scope != store.MASTER_SCOPE and store.latest_version(db, scope) is None:
        raise HTTPException(status_code=404, detail=f"no CV versions for scope {scope!r}")
    row = store.save_version(db, scope, document, author=author)
    await manager.broadcast({"type": "cv_updated", "scope": scope, "version": row.version})
    return CvDocumentOut(scope=scope, version=row.version, document=document)


@router.post("/{scope}/compile", response_model=CvCompileOut)
async def compile_cv(scope: str, db: Session = Depends(get_db)) -> CvCompileOut:
    """Build the current version to PDF via the Docker LaTeX image (slow: ~10-30s)."""
    doc = _load(db, scope)
    row = store.latest_version(db, scope)
    try:
        result = compile_document(doc, scope)
    except BuildError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Compiling answers "does this build?". It does not answer "can a machine
    # read what it built?", and the second is what decides whether a human ever
    # sees the CV. Checked here, while there is still a build to fix.
    report = check_build(result, doc, _job_skills(db, scope))
    out = CvCompileOut(
        scope=scope,
        version=row.version if row else 0,
        pages=result.pages,
        pdf_url=f"/cv/{scope}/pdf",
        ats=report.as_dict() if report else None,
    )
    await manager.broadcast(
        {
            "type": "cv_compiled",
            "scope": scope,
            "pages": result.pages,
            "ats_ok": report.ok if report else None,
        }
    )
    return out


def _job_skills(db: Session, scope: str) -> list[str] | None:
    """Skills of the job a tailored CV targets, for the keyword coverage check.

    A Master CV answers to no job, so it gets no keyword check: reporting
    "missing keyword" against nothing invites padding the CV with skills you
    don't have, which is the exact thing the tailor guardrail exists to stop.
    """
    if scope == store.MASTER_SCOPE:
        return None
    job = db.get(Job, scope)
    return list((job.payload or {}).get("skills") or []) if job else None


@router.get("/{scope}/pdf")
def get_pdf(scope: str) -> FileResponse:
    """Serve the last compiled PDF for the scope."""
    pdf = build_dir(scope) / "cv.pdf"
    if not pdf.is_file():
        raise HTTPException(status_code=404, detail="not compiled yet — POST /cv/{scope}/compile")
    return FileResponse(pdf, media_type="application/pdf", filename=f"{scope}-cv.pdf")


@router.get("/{scope}/versions", response_model=list[CvVersionOut])
def versions(scope: str, db: Session = Depends(get_db)) -> list[CvVersionOut]:
    """Version metadata, newest first (content omitted -- it's heavy)."""
    if scope == store.MASTER_SCOPE:
        store.ensure_master(db)
    return [CvVersionOut.model_validate(v) for v in store.list_versions(db, scope)]


@router.get("/{scope}/versions/{version}", response_model=CvVersionDetailOut)
def version_detail(scope: str, version: int, db: Session = Depends(get_db)) -> CvVersionDetailOut:
    """Full content + ``.tex`` snapshot of one version (used for diffing)."""
    row = store.get_version(db, scope, version)
    if row is None:
        raise HTTPException(status_code=404, detail=f"scope {scope!r} has no version {version}")
    return CvVersionDetailOut(
        **CvVersionOut.model_validate(row).model_dump(),
        document=CvDocument.model_validate(row.content),
        tex=row.tex_snapshot or render_tex_snapshot(CvDocument.model_validate(row.content)),
    )


@router.get("/{scope}/diff", response_model=CvVersionDiffOut)
def version_diff(
    scope: str,
    base: int,
    target: int,
    db: Session = Depends(get_db),
) -> CvVersionDiffOut:
    """Structural diff between any two versions of a scope (``base`` -> ``target``).

    Same walker the CV Review page uses, with neutral wording: here a disabled
    section means you switched it off, not that an agent dropped it for a job.
    """
    rows = {}
    # dict.fromkeys: dedupes base == target (one row, one query) while keeping
    # base first, so "both missing" reports the base version rather than a
    # version the caller has to guess the order of.
    for version in dict.fromkeys((base, target)):
        row = store.get_version(db, scope, version)
        if row is None:
            raise HTTPException(
                status_code=404, detail=f"scope {scope!r} has no version {version}"
            )
        rows[version] = row
    return CvVersionDiffOut(
        scope=scope,
        base=base,
        target=target,
        base_author=rows[base].author,
        target_author=rows[target].author,
        diff=diff_documents(
            CvDocument.model_validate(rows[base].content),
            CvDocument.model_validate(rows[target].content),
            labels=VERSION_LABELS,
        ),
    )


@router.post("/{scope}/rollback/{version}", response_model=CvDocumentOut)
async def rollback_cv(scope: str, version: int, db: Session = Depends(get_db)) -> CvDocumentOut:
    """Re-save an older version as the newest one (history is preserved)."""
    try:
        row = store.rollback(db, scope, version)
    except store.ScopeNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    doc = CvDocument.model_validate(row.content)
    await manager.broadcast({"type": "cv_updated", "scope": scope, "version": row.version})
    return CvDocumentOut(scope=scope, version=row.version, document=doc)
