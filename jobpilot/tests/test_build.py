"""Phase 1: build wrapper unit tests (no Docker needed)."""

import pytest

from jobpilot.tailor import build as build_mod
from jobpilot.tailor.build import BuildError, _pages_from_log, _pages_from_pdf, build_cv


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
