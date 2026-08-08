"""Phase 4.5: cv_versions history (append-only, seeding, rollback) + build dirs."""

from __future__ import annotations

import pytest

from jobpilot.cv import store
from jobpilot.cv.compile import (
    ASSETS,
    UnsafeTexPath,
    build_dir,
    prepare_build_dir,
    scope_slug,
)
from jobpilot.cv.schema import CvDocument, Header, ParagraphSection
from jobpilot.store.models import CvVersion


@pytest.fixture
def db(session_factory):
    with session_factory() as s:
        yield s


def _doc(text: str) -> CvDocument:
    return CvDocument(
        header=Header(first_name="A", last_name="B"),
        sections=[ParagraphSection(key="summary", title="Summary", text=text)],
    )


def test_resolve_scope_maps_master_and_job_ids():
    assert store.resolve_scope("master") == ("master", None)
    assert store.resolve_scope("itviec:42") == ("tailored", "itviec:42")


def test_get_document_seeds_master_on_first_use(db):
    assert store.latest_version(db, "master") is None
    doc = store.get_document(db, "master")
    assert doc.header.first_name == "ALEX"
    assert store.latest_version(db, "master").version == 1


def test_ensure_master_is_idempotent(db):
    first = store.ensure_master(db)
    second = store.ensure_master(db)
    assert first.version == second.version == 1
    assert db.query(CvVersion).count() == 1


def test_saves_are_append_only_and_numbered(db):
    store.save_version(db, "master", _doc("v1"))
    store.save_version(db, "master", _doc("v2"), author="agent")
    versions = store.list_versions(db, "master")
    assert [v.version for v in versions] == [2, 1]  # newest first
    assert versions[0].author == "agent"
    assert store.get_document(db, "master").sections[0].text == "v2"
    # v1's content is untouched.
    assert store.get_version(db, "master", 1).content["sections"][0]["text"] == "v1"


def test_save_records_a_tex_snapshot(db):
    row = store.save_version(db, "master", _doc("hello"))
    assert r"\cvsection{Summary}" in row.tex_snapshot
    assert row.theme["color"] == "awesome-red"


def test_rollback_appends_rather_than_rewriting(db):
    store.save_version(db, "master", _doc("v1"))
    store.save_version(db, "master", _doc("v2"))
    row = store.rollback(db, "master", 1)
    assert row.version == 3
    assert store.get_document(db, "master").sections[0].text == "v1"
    assert [v.version for v in store.list_versions(db, "master")] == [3, 2, 1]


def test_rollback_to_missing_version_raises(db):
    store.ensure_master(db)
    with pytest.raises(store.ScopeNotFound):
        store.rollback(db, "master", 99)


def test_tailored_scope_is_not_auto_seeded(db):
    with pytest.raises(store.ScopeNotFound):
        store.get_document(db, "itviec:1")


def test_tailored_scopes_have_independent_history(db):
    store.ensure_master(db)
    store.save_version(db, "itviec:1", _doc("tailored-a"))
    store.save_version(db, "itviec:2", _doc("tailored-b"))
    assert store.get_document(db, "itviec:1").sections[0].text == "tailored-a"
    assert store.get_document(db, "itviec:2").sections[0].text == "tailored-b"
    assert store.get_document(db, "master").header.first_name == "ALEX"
    # Each fresh scope starts its own numbering.
    assert store.latest_version(db, "itviec:2").version == 1


def test_fork_from_master_copies_current_master(db):
    store.save_version(db, "master", _doc("master-text"))
    row = store.fork_from_master(db, "itviec:9")
    assert row.author == "agent"
    assert store.get_document(db, "itviec:9").sections[0].text == "master-text"


# --------------------------------------------------------------------------- #
# compile.py (everything up to the Docker call, which needs a real daemon)
# --------------------------------------------------------------------------- #
def test_scope_slug_is_filesystem_safe():
    assert scope_slug("master") == "master"
    assert scope_slug("itviec:some/id") == "itviec_some_id"
    assert scope_slug("///") == "unnamed"


def test_build_dir_separates_scopes(tmp_path):
    assert build_dir("master", tmp_path) != build_dir("itviec:1", tmp_path)


def test_prepare_build_dir_writes_project_and_assets(tmp_path):
    dest = prepare_build_dir(_doc("hi"), "master", tmp_path)
    assert (dest / "cv.tex").is_file()
    assert (dest / "resume" / "summary.tex").is_file()
    for asset in ASSETS:
        assert (dest / asset).exists()


def test_rerender_drops_orphaned_section_files(tmp_path):
    dest = prepare_build_dir(_doc("hi"), "master", tmp_path)
    stale = dest / "resume" / "old.tex"
    stale.write_text("stale", encoding="utf-8")
    prepare_build_dir(_doc("hi again"), "master", tmp_path)
    assert not stale.exists()
    assert (dest / "resume" / "summary.tex").is_file()


def test_prepare_build_dir_never_touches_the_master_resume_dir(tmp_path):
    """CLAUDE.md rule 3: tailored builds must not overwrite the Master CV."""
    from jobpilot.config import REPO_ROOT

    dest = prepare_build_dir(_doc("hi"), "itviec:1", tmp_path)
    assert REPO_ROOT not in dest.parents and dest != REPO_ROOT
    assert tmp_path in dest.parents


# --------------------------------------------------------------------------- #
# Raw LaTeX override
# --------------------------------------------------------------------------- #
def test_override_is_written_over_the_rendered_project(tmp_path):
    """Overriding one file leaves the others tracking the JSON."""
    dest = prepare_build_dir(_doc("hi"), "master", tmp_path, override={"cv.tex": "% mine\n"})
    assert (dest / "cv.tex").read_text(encoding="utf-8") == "% mine\n"
    assert "hi" in (dest / "resume" / "summary.tex").read_text(encoding="utf-8")


def test_dropping_the_override_restores_the_generated_file(tmp_path):
    prepare_build_dir(_doc("hi"), "master", tmp_path, override={"cv.tex": "% mine\n"})
    dest = prepare_build_dir(_doc("hi"), "master", tmp_path)
    assert "% mine" not in (dest / "cv.tex").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "path",
    # The two backslash cases matter on Windows, where PurePosixPath reads
    # "a\\b.tex" as one harmless-looking segment rather than as a path.
    ["/abs.tex", "../out.tex", "a/../../b.tex", "cv.sh", "a\\b.tex", "..\\escape.tex"],
)
def test_override_paths_that_leave_the_build_dir_are_rejected(tmp_path, path):
    with pytest.raises(UnsafeTexPath):
        prepare_build_dir(_doc("hi"), "master", tmp_path, override={path: "x"})


def test_override_round_trips_through_a_version(db):
    store.ensure_master(db)
    assert store.latest_tex_override(db, "master") is None
    store.save_tex_override(db, "master", {"cv.tex": "% mine\n"})
    assert store.latest_tex_override(db, "master") == {"cv.tex": "% mine\n"}
    store.save_tex_override(db, "master", None)
    assert store.latest_tex_override(db, "master") is None
