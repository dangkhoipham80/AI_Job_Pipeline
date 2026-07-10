"""Compile an Awesome-CV LaTeX project to PDF via the Docker builder image.

The `csmith/awesome-cv-builder` image (see README.md) compiles `cv.tex` in the
mounted `/work` dir and emits `cv.pdf`. This wrapper runs it, then reports the
page count (parsed from the xelatex `.log`, with a PDF fallback).
"""

from __future__ import annotations

import re
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
    pages: int
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
    cmd = ["docker", "run", "--rm", "-v", f"{work_dir}:/work", image]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - env dependent
        raise BuildError(f"LaTeX build timed out after {timeout}s") from exc

    pdf = work_dir / f"{stem}.pdf"
    if proc.returncode != 0 or not pdf.is_file():
        tail = (proc.stdout or "")[-1500:] + "\n" + (proc.stderr or "")[-1500:]
        raise BuildError(f"LaTeX build failed (rc={proc.returncode}).\n{tail}")

    pages = _pages_from_pdf(pdf) or _pages_from_log(work_dir / f"{stem}.log") or 0
    return BuildResult(pdf=pdf, pages=pages, log_tail=(proc.stdout or "")[-500:])
