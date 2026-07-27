"""Version history for CV documents (``cv_versions``, PLAN.md §3.2 / §5.6.1).

Every save appends a row -- nothing is mutated in place, so rollback is just
"save the old content again as a new version" and the audit trail stays intact.

Scope strings used by the API and CLI:
    "master"  -> the Master CV        (scope='master',   job_id=NULL)
    "<job_id>"-> a tailored CV        (scope='tailored', job_id=<job_id>)
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobpilot.cv.render import render_tex_snapshot
from jobpilot.cv.schema import CvDocument
from jobpilot.store.models import CvVersion

MASTER_SCOPE = "master"
SEED_PATH = Path(__file__).resolve().parent / "master_seed.json"


class ScopeNotFound(LookupError):
    """No version exists yet for the requested scope."""


def resolve_scope(scope: str) -> tuple[str, str | None]:
    """API scope string -> (``cv_versions.scope``, ``job_id``)."""
    if scope == MASTER_SCOPE:
        return MASTER_SCOPE, None
    return "tailored", scope


def load_seed() -> CvDocument:
    """The Master CV imported once from the original ``resume/*.tex`` (PLAN.md §9)."""
    return CvDocument.model_validate(json.loads(SEED_PATH.read_text(encoding="utf-8")))


def _scoped(scope: str):
    kind, job_id = resolve_scope(scope)
    stmt = select(CvVersion).where(CvVersion.scope == kind)
    return stmt.where(CvVersion.job_id.is_(None) if job_id is None else CvVersion.job_id == job_id)


def list_versions(db: Session, scope: str) -> list[CvVersion]:
    """Newest first."""
    return list(db.scalars(_scoped(scope).order_by(CvVersion.version.desc())))


def latest_version(db: Session, scope: str) -> CvVersion | None:
    return db.scalars(_scoped(scope).order_by(CvVersion.version.desc()).limit(1)).first()


def get_version(db: Session, scope: str, version: int) -> CvVersion | None:
    return db.scalars(_scoped(scope).where(CvVersion.version == version)).first()


def save_version(
    db: Session,
    scope: str,
    doc: CvDocument,
    author: str = "user",
    meta: dict | None = None,
    commit: bool = True,
) -> CvVersion:
    """Append a new version. ``author`` distinguishes hand edits from agent tailoring.

    ``meta`` carries the tailor output (plan, gaps, diff) for agent versions.
    """
    kind, job_id = resolve_scope(scope)
    previous = latest_version(db, scope)
    row = CvVersion(
        scope=kind,
        job_id=job_id,
        version=(previous.version + 1) if previous else 1,
        content=doc.model_dump(mode="json"),
        tex_snapshot=render_tex_snapshot(doc),
        theme=doc.theme.model_dump(mode="json"),
        author=author,
        meta=meta or {},
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def ensure_master(db: Session) -> CvVersion:
    """Seed the Master CV from ``master_seed.json`` on first use; idempotent."""
    existing = latest_version(db, MASTER_SCOPE)
    if existing is not None:
        return existing
    return save_version(db, MASTER_SCOPE, load_seed(), author="user")


def get_document(db: Session, scope: str) -> CvDocument:
    """Current document for ``scope``. Auto-seeds ``master``; raises otherwise."""
    row = latest_version(db, scope)
    if row is None:
        if scope == MASTER_SCOPE:
            row = ensure_master(db)
        else:
            raise ScopeNotFound(f"no CV versions for scope {scope!r}")
    return CvDocument.model_validate(row.content)


def rollback(db: Session, scope: str, version: int) -> CvVersion:
    """Re-save an older version as the newest one (history is never rewritten)."""
    target = get_version(db, scope, version)
    if target is None:
        raise ScopeNotFound(f"scope {scope!r} has no version {version}")
    doc = CvDocument.model_validate(target.content)
    return save_version(db, scope, doc, author=target.author)


def fork_from_master(db: Session, job_id: str, author: str = "agent") -> CvVersion:
    """Start a tailored CV for ``job_id`` as a copy of the current Master (Phase 5)."""
    return save_version(db, job_id, get_document(db, MASTER_SCOPE), author=author)
