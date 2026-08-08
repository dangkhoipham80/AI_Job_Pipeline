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
from jobpilot.cv.skeleton import empty_document
from jobpilot.store.models import CvVersion

MASTER_SCOPE = "master"


class ScopeNotFound(LookupError):
    """No version exists yet for the requested scope."""


def resolve_scope(scope: str) -> tuple[str, str | None]:
    """API scope string -> (``cv_versions.scope``, ``job_id``)."""
    if scope == MASTER_SCOPE:
        return MASTER_SCOPE, None
    return "tailored", scope


def read_document(path: Path) -> CvDocument:
    """Load a CV document from a JSON file (for ``jobpilot cv import``).

    Top-level keys starting with ``_`` are dropped, so an exported file can carry
    a ``_comment`` — JSON has no comment syntax.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return CvDocument.model_validate({k: v for k, v in data.items() if not k.startswith("_")})


def _scoped(scope: str):
    kind, job_id = resolve_scope(scope)
    stmt = select(CvVersion).where(CvVersion.scope == kind)
    return stmt.where(CvVersion.job_id.is_(None) if job_id is None else CvVersion.job_id == job_id)


def list_versions(
    db: Session, scope: str, limit: int | None = None, offset: int = 0
) -> list[CvVersion]:
    """Newest first. ``limit=None`` is every version — what the CLI wants."""
    # (scope, job_id, version) is unique, so ordering by version is already total.
    stmt = _scoped(scope).order_by(CvVersion.version.desc()).offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt))


def count_versions(db: Session, scope: str) -> int:
    """How many versions this scope has, ignoring any page window."""
    from sqlalchemy import func

    return db.scalar(select(func.count()).select_from(_scoped(scope).subquery())) or 0


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


#: Key under ``cv_versions.meta`` holding a hand-edited LaTeX project.
TEX_OVERRIDE_KEY = "tex_override"


def latest_tex_override(db: Session, scope: str) -> dict[str, str] | None:
    """Raw ``.tex`` the newest version builds from, or ``None`` for the rendered one.

    Lives in ``meta`` rather than a column because it is an exception, not a
    second source of truth: the structured JSON in ``content`` still describes
    the CV, and the override records that a human overruled how it serializes.
    """
    row = latest_version(db, scope)
    if row is None:
        return None
    files = (row.meta or {}).get(TEX_OVERRIDE_KEY)
    return dict(files) if files else None


def save_tex_override(
    db: Session, scope: str, files: dict[str, str] | None, author: str = "user"
) -> CvVersion:
    """Append a version whose document is unchanged but whose LaTeX is (or isn't) overridden.

    ``files=None`` clears the override, which is how you get back to the
    round-tripping editor: the next build renders from the JSON again.
    """
    doc = get_document(db, scope)
    meta = {TEX_OVERRIDE_KEY: files} if files else {}
    return save_version(db, scope, doc, author=author, meta=meta)


def ensure_master(db: Session) -> CvVersion:
    """Create an empty Master CV on first use; idempotent.

    Empty, not pre-filled: the repository holds no CV content, so there is
    nothing to seed from. You fill it in CV Studio (which reads and writes it
    through the API) or import an existing document with ``jobpilot cv import``.
    """
    existing = latest_version(db, MASTER_SCOPE)
    if existing is not None:
        return existing
    return save_version(db, MASTER_SCOPE, empty_document(), author="user")


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
    """Re-save an older version as the newest one (history is never rewritten).

    The target's raw-LaTeX override comes back with it. "Restore v7" has to mean
    the PDF v7 built; carrying the document but not the ``.tex`` it was actually
    compiled from would restore a version that never existed.
    """
    target = get_version(db, scope, version)
    if target is None:
        raise ScopeNotFound(f"scope {scope!r} has no version {version}")
    doc = CvDocument.model_validate(target.content)
    override = (target.meta or {}).get(TEX_OVERRIDE_KEY)
    return save_version(
        db,
        scope,
        doc,
        author=target.author,
        meta={TEX_OVERRIDE_KEY: dict(override)} if override else None,
    )


def fork_from_master(db: Session, job_id: str, author: str = "agent") -> CvVersion:
    """Start a tailored CV for ``job_id`` as a copy of the current Master (Phase 5)."""
    return save_version(db, job_id, get_document(db, MASTER_SCOPE), author=author)
