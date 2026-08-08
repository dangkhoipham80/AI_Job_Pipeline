"""Compile a ``CvDocument`` to PDF: JSON -> .tex -> Docker LaTeX -> cv.pdf.

Each scope ("master", or ``job:<id>`` for a tailored CV) gets its own build dir
under ``out/cv/<scope>/`` so builds never touch the tracked Master ``resume/``
(CLAUDE.md rule 3). The Awesome-CV class, fontawesome.sty and fonts/ are copied
in once per build dir and reused.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path, PurePosixPath

from jobpilot.config import REPO_ROOT, get_config
from jobpilot.cv.ats import AtsReport, check_pdf
from jobpilot.cv.render import write_document
from jobpilot.cv.schema import CvDocument
from jobpilot.tailor.build import BuildResult, build_cv

MASTER_SCOPE = "master"

# Files/dirs the generated cv.tex needs alongside it, sourced from the repo root.
ASSETS = ("awesome-cv.cls", "fontawesome.sty", "fonts")

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def scope_slug(scope: str) -> str:
    """Filesystem-safe dir name for a scope (job ids contain ':' and '/')."""
    slug = _UNSAFE.sub("_", scope).strip("_")
    return slug or "unnamed"


def build_dir(scope: str = MASTER_SCOPE, root: Path | None = None) -> Path:
    base = root or (REPO_ROOT / get_config().cv.out_dir)
    return base / "cv" / scope_slug(scope)


def sync_assets(dest: Path, source: Path | None = None) -> None:
    """Copy the LaTeX class/fonts into ``dest`` (skipping what's already there)."""
    source = source or REPO_ROOT
    dest.mkdir(parents=True, exist_ok=True)
    for name in ASSETS:
        src, dst = source / name, dest / name
        if not src.exists() or dst.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


class UnsafeTexPath(ValueError):
    """A raw-LaTeX override named a file the build dir has no business holding."""


def check_override(files: dict[str, str]) -> dict[str, str]:
    """Validate the paths of a raw ``.tex`` override; returns it unchanged.

    These strings become filesystem paths under ``out/cv/<scope>/``, so they are
    checked rather than trusted: relative, no traversal, ``.tex`` only. A
    hand-edited CV is not a threat model on a single-user local box, but "text
    from a text box turns into a path" is the shape of bug that only ever gets
    noticed the expensive way.
    """
    for path in files:
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or "\\" in path:
            raise UnsafeTexPath(f"{path!r} must be a relative path inside the build dir")
        if pure.suffix != ".tex":
            raise UnsafeTexPath(f"{path!r} must be a .tex file")
    return files


def prepare_build_dir(
    doc: CvDocument,
    scope: str = MASTER_SCOPE,
    root: Path | None = None,
    override: dict[str, str] | None = None,
) -> Path:
    """Materialize the full LaTeX project for ``doc`` and return its directory.

    ``override`` is written *over* the rendered project rather than instead of
    it, so editing ``cv.tex`` by hand doesn't oblige you to also hand-write every
    section file — the ones you left alone keep tracking the JSON.
    """
    dest = build_dir(scope, root)
    sync_assets(dest)
    write_document(doc, dest)
    for rel, text in check_override(override or {}).items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return dest


def compile_document(
    doc: CvDocument,
    scope: str = MASTER_SCOPE,
    root: Path | None = None,
    override: dict[str, str] | None = None,
) -> BuildResult:
    """Render + build. Raises ``BuildError`` if LaTeX or Docker fails."""
    return build_cv(prepare_build_dir(doc, scope, root, override))


def check_build(
    result: BuildResult, doc: CvDocument, job_skills: list[str] | None = None
) -> AtsReport | None:
    """Read the PDF back the way an applicant tracking system would.

    Kept separate from :func:`compile_document` on purpose: compiling answers
    "does this build?", this answers "can a machine read what it built?" — two
    questions that fail independently and want different remedies. ``None``
    means the text layer could not be read at all (pypdf missing), which is
    "not checked" rather than "passed".
    """
    return check_pdf(result.pdf, doc, job_skills)
