"""Phase 1: build wrapper unit tests (no Docker needed)."""

import pytest

from jobpilot.tailor import build as build_mod
from jobpilot.tailor.build import (
    BuildError,
    _pages_from_log,
    _pages_from_pdf,
    build_cv,
    page_summary,
)


def test_build_raises_when_entry_missing(tmp_path):
    with pytest.raises(BuildError, match="entry not found"):
        build_cv(tmp_path, entry="nope.tex")


def test_build_raises_when_docker_absent(tmp_path, monkeypatch):
    (tmp_path / "cv.tex").write_text("\\documentclass{article}", encoding="utf-8")
    monkeypatch.setattr(build_mod.shutil, "which", lambda _: None)
    with pytest.raises(BuildError, match="docker not found"):
        build_cv(tmp_path, entry="cv.tex")


def test_pages_from_log(tmp_path):
    log = tmp_path / "cv.log"
    log.write_text("Output written on cv.pdf (1 page, 36973 bytes).", encoding="utf-8")
    assert _pages_from_log(log) == 1


def test_pages_from_log_multi(tmp_path):
    log = tmp_path / "cv.log"
    log.write_text("blah\nOutput written on cv.pdf (2 pages, 1234 bytes).\n", encoding="utf-8")
    assert _pages_from_log(log) == 2


def test_pages_from_log_missing(tmp_path):
    assert _pages_from_log(tmp_path / "absent.log") is None


def test_pages_from_pdf_counts_page_objects(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.5\n1 0 obj<</Type /Page>>endobj\n<</Type /Pages /Count 1>>")
    assert _pages_from_pdf(pdf) == 1


def test_an_unreadable_page_count_is_unknown_not_zero(tmp_path, monkeypatch):
    """A real xelatex PDF stores its objects in compressed streams, so with pypdf
    missing the regex finds nothing — and the builder image leaves no .log to
    fall back to. Reporting 0 then badges a perfectly good CV as "0 pages" in
    red; the honest answer is that we don't know."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "cv.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}", "utf-8")
    (work / "cv.pdf").write_bytes(b"%PDF-1.5\n<compressed object streams>\n%%EOF")
    monkeypatch.setattr(build_mod.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(
        build_mod.subprocess,
        "run",
        lambda *a, **k: type("P", (), {"returncode": 0, "stdout": ""})(),
    )
    assert build_cv(work, entry="cv.tex").pages is None


def test_page_summary_says_unknown_rather_than_warning_about_none_pages():
    assert page_summary(1) == "OK: 1 page"
    assert "WARNING" in page_summary(2)
    assert "unknown" in page_summary(None)
