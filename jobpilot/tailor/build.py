"""Compile an Awesome-CV LaTeX project to PDF via the Docker builder image.

The `csmith/awesome-cv-builder` image (see README.md) mounts `/work` and runs
xelatex. This wrapper runs it, then reports the page count (parsed from the
xelatex `.log`, with a PDF fallback).

The image's built-in command hardcodes `cv.tex`:

    /bin/sh -c 'DIR=$(mktemp -d); xelatex -output-directory=$DIR cv.tex; \
                mv $DIR/cv.pdf .; rm -rf $DIR'

so passing ``entry="cover_letter.tex"`` and letting the image do its thing would
rebuild the CV and then fail looking for a PDF nobody asked it to make. We spell
the command out instead, which is the only way ``entry`` means anything. The
default path renders the same command the image ships with.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from jobpilot.config import get_config


class BuildError(RuntimeError):
    """Raised when the LaTeX build fails or produces no PDF."""


@dataclass
class BuildResult:
    pdf: Path
    #: None when the page count could not be established (see ``build_cv``).
    pages: int | None
    log_tail: str = ""


def _pages_from_log(log_path: Path) -> int | None:
    """xelatex writes e.g. 'Output written on cv.pdf (1 page, 36973 bytes).'"""
    if not log_path.is_file():
        return None
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"Output written on .*?\((\d+)\s+page", text)
    return int(m.group(1)) if m else None


def _pages_from_pdf(pdf_path: Path) -> int | None:
    """Authoritative count via pypdf; fall back to regex if unavailable/unparseable.

    (The Docker builder's xelatex log is unreliable — it can report '1 page' for a
    2-page PDF — so the PDF itself is the source of truth.)
    """
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(pdf_path)).pages)
    except ImportError:
        pass
    except Exception:
        pass  # malformed/edge PDF — try regex below

    data = pdf_path.read_bytes()
    pages = len(re.findall(rb"/Type\s*/Page(?![s])", data))
    if pages:
        return pages
    counts = [int(c) for c in re.findall(rb"/Count\s+(\d+)", data)]
    return max(counts) if counts else None


def page_summary(pages: int | None) -> str:
    """One line about the page budget, for the CLI. A CV should be one page."""
    if pages is None:
        return "page count unknown — pip install -e '.[cv]' for pypdf"
    return "OK: 1 page" if pages == 1 else f"WARNING: {pages} pages (CV should be 1)"


def _script(entry: str) -> str:
    """The image's own command, with the entry file made explicit.

    xelatex writes to a temp dir so a failed run leaves no half-written PDF next
    to the source for the caller to mistake for a success.
    """
    stem = Path(entry).stem
    # Quoted even though every caller passes a repo constant: this string is a
    # shell command, and the moment an entry has a space in it an unquoted one
    # splits into two tokens and xelatex reports a missing file that isn't the
    # one you named.
    return (
        f"DIR=$(mktemp -d); xelatex -output-directory=$DIR {shlex.quote(entry)}; "
        f"mv $DIR/{shlex.quote(stem + '.pdf')} .; rm -rf $DIR"
    )


def build_cv(
    work_dir: Path | str,
    entry: str = "cv.tex",
    image: str | None = None,
    timeout: int = 300,
) -> BuildResult:
    work_dir = Path(work_dir).resolve()
    stem = Path(entry).stem
    if not (work_dir / entry).is_file():
        raise BuildError(f"entry not found: {work_dir / entry}")
    if shutil.which("docker") is None:
        raise BuildError("docker not found on PATH — is Docker installed and running?")

    image = image or get_config().cv.docker_image
    pdf = work_dir / f"{stem}.pdf"
    # Drop the previous PDF first. The image's command is `xelatex …; mv …; rm …`
    # with no `set -e`, so a LaTeX error still exits 0 (the trailing `rm` decides
    # the status) and the only tell that the build failed is the missing PDF —
    # which yesterday's file would answer for. That reports success and hands
    # back stale content, the worst of the two failure modes.
    pdf.unlink(missing_ok=True)

    mount = f"{work_dir}:/work"
    cmd = ["docker", "run", "--rm", "-v", mount, image, "/bin/sh", "-c", _script(entry)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - env dependent
        raise BuildError(f"LaTeX build timed out after {timeout}s") from exc

    if proc.returncode != 0 or not pdf.is_file():
        tail = (proc.stdout or "")[-1500:] + "\n" + (proc.stderr or "")[-1500:]
        raise BuildError(f"LaTeX build failed (rc={proc.returncode}).\n{tail}")

    # None when nothing could read it — "unknown" and "zero pages" are different
    # claims, and a CV that built fine should not be badged as 0 pages in red.
    # That is the live failure mode when pypdf is missing: xelatex writes its PDF
    # with compressed object streams, so the regex fallback finds no /Type /Page,
    # and the builder image doesn't leave a .log behind either.
    pages = _pages_from_pdf(pdf) or _pages_from_log(work_dir / f"{stem}.log")
    return BuildResult(pdf=pdf, pages=pages, log_tail=(proc.stdout or "")[-500:])
