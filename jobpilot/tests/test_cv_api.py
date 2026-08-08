"""Phase 4.5: CV Studio API (read/save/versions/rollback/compile/pdf)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobpilot.api.deps import get_db
from jobpilot.api.main import app
from jobpilot.config import get_secrets
from jobpilot.tailor.build import BuildError

TOKEN = get_secrets().jobpilot_api_token
AUTH = {"X-API-Token": TOKEN}


@pytest.fixture
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _master(client) -> dict:
    r = client.get("/cv/master", headers=AUTH)
    assert r.status_code == 200
    return r.json()


def test_cv_requires_token(client):
    assert client.get("/cv/master").status_code == 401
    assert client.get("/cv/templates").status_code == 401


def test_get_master_auto_seeds(client):
    body = _master(client)
    assert body["version"] == 1
    assert body["document"]["header"]["first_name"] == "ALEX"
    assert [s["key"] for s in body["document"]["sections"]] == [
        "summary",
        "education",
        "experience",
        "projects",
        "honors",
        "skills",
    ]


def test_templates_route_is_not_shadowed_by_scope(client):
    r = client.get("/cv/templates", headers=AUTH)
    assert r.status_code == 200
    assert "awesome_cv" in r.json()["templates"]


def test_put_appends_a_version(client):
    doc = _master(client)["document"]
    doc["header"]["position"] = "Backend Engineer"
    r = client.put("/cv/master", headers=AUTH, json=doc)
    assert r.status_code == 200
    assert r.json()["version"] == 2
    assert _master(client)["document"]["header"]["position"] == "Backend Engineer"


def test_put_rejects_an_invalid_document(client):
    r = client.put("/cv/master", headers=AUTH, json={"sections": [{"type": "nope"}]})
    assert r.status_code == 422


def test_put_rejects_unknown_tailored_scope(client):
    doc = _master(client)["document"]
    assert client.put("/cv/itviec:missing", headers=AUTH, json=doc).status_code == 404


def test_versions_list_and_detail(client):
    doc = _master(client)["document"]
    doc["header"]["position"] = "v2"
    client.put("/cv/master?author=agent", headers=AUTH, json=doc)

    rows = client.get("/cv/master/versions", headers=AUTH).json()["items"]
    assert [r["version"] for r in rows] == [2, 1]
    assert rows[0]["author"] == "agent"

    detail = client.get("/cv/master/versions/1", headers=AUTH).json()
    assert detail["document"]["header"]["position"] == "Fresher Software Engineer"
    assert r"\cvsection{Summary}" in detail["tex"]


def test_version_detail_404(client):
    _master(client)
    assert client.get("/cv/master/versions/99", headers=AUTH).status_code == 404


def test_rollback_restores_content_as_a_new_version(client):
    doc = _master(client)["document"]
    doc["header"]["position"] = "v2"
    client.put("/cv/master", headers=AUTH, json=doc)

    r = client.post("/cv/master/rollback/1", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["version"] == 3
    assert r.json()["document"]["header"]["position"] == "Fresher Software Engineer"


def test_rollback_404(client):
    _master(client)
    assert client.post("/cv/master/rollback/99", headers=AUTH).status_code == 404


def test_unknown_scope_404(client):
    assert client.get("/cv/itviec:nope", headers=AUTH).status_code == 404


def _diff(client, base: int, target: int):
    return client.get(f"/cv/master/diff?base={base}&target={target}", headers=AUTH)


def test_diff_reports_what_changed_between_two_versions(client):
    doc = _master(client)["document"]
    doc["sections"] = [s for s in doc["sections"] if s["key"] != "honors"]
    for s in doc["sections"]:
        if s["key"] == "summary":
            s["text"] = "Rewritten by hand."
    client.put("/cv/master", headers=AUTH, json=doc)

    body = _diff(client, 1, 2).json()
    assert (body["base"], body["target"]) == (1, 2)
    assert body["base_author"] == body["target_author"] == "user"

    by_key = {s["key"]: s for s in body["diff"]["sections"]}
    assert by_key["summary"]["status"] == "rewritten"
    assert by_key["summary"]["after"] == "Rewritten by hand."
    assert by_key["honors"]["status"] == "hidden"


def test_diff_uses_neutral_wording_not_the_tailors(client):
    """A hand edit in Studio is not "hidden to keep it to one page" — no agent
    decided anything here, and captioning it that way invents a reason."""
    doc = _master(client)["document"]
    doc["sections"] = [s for s in doc["sections"] if s["key"] != "honors"]
    client.put("/cv/master", headers=AUTH, json=doc)

    notes = [n for s in _diff(client, 1, 2).json()["diff"]["sections"] for n in s["notes"]]
    assert "section deleted" in notes
    assert not any("this role" in n or "one page" in n for n in notes)


def test_diff_of_a_version_against_itself_is_empty(client):
    _master(client)
    diff = _diff(client, 1, 1).json()["diff"]
    assert diff["order_changed"] is False
    assert all(s["status"] == "unchanged" for s in diff["sections"])
    # `changed` is a computed_field. Drop the decorator and it silently vanishes
    # from the JSON — the UI reads `undefined` as falsy and never complains.
    assert diff["changed"] is False


def test_diff_serializes_the_changed_flag(client):
    doc = _master(client)["document"]
    doc["sections"] = [s for s in doc["sections"] if s["key"] != "honors"]
    client.put("/cv/master", headers=AUTH, json=doc)
    assert _diff(client, 1, 2).json()["diff"]["changed"] is True


def test_diff_404_on_a_missing_version(client):
    _master(client)
    assert _diff(client, 1, 99).status_code == 404
    assert _diff(client, 99, 1).status_code == 404


def test_diff_route_is_not_shadowed_by_the_version_detail_route(client):
    """/cv/{scope}/diff must not be read as /cv/{scope}/versions/{version}."""
    _master(client)
    assert _diff(client, 1, 1).status_code == 200


def test_pdf_404_before_compile(client, monkeypatch, tmp_path):
    monkeypatch.setattr("jobpilot.api.routes.cv.build_dir", lambda scope: tmp_path / scope)
    assert client.get("/cv/master/pdf", headers=AUTH).status_code == 404


def test_compile_returns_page_count(client, monkeypatch, tmp_path):
    class FakeResult:
        pages = 1
        pdf = tmp_path / "cv.pdf"  # never written → the text layer is unreadable

    monkeypatch.setattr("jobpilot.api.routes.cv.compile_document", lambda doc, scope, override=None: FakeResult())
    r = client.post("/cv/master/compile", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {
        "scope": "master",
        "version": 1,
        "pages": 1,
        "pdf_url": "/cv/master/pdf",
        # No readable PDF means "not checked". Reporting ok here would be a pass
        # the checker never granted.
        "ats": None,
    }


def test_compile_reports_what_a_parser_gets_back(client, monkeypatch, tmp_path):
    """CV Review needs the findings *before* you approve, not after the silence."""
    from jobpilot.cv.ats import AtsReport, Finding

    class FakeResult:
        pages = 1
        pdf = tmp_path / "cv.pdf"

    report = AtsReport(
        ok=False,
        chars=1200,
        findings=[
            Finding("error", "email_missing", "no email in the text layer", "fix the header")
        ],
    )
    monkeypatch.setattr("jobpilot.api.routes.cv.compile_document", lambda doc, scope, override=None: FakeResult())
    monkeypatch.setattr("jobpilot.cv.compile.check_pdf", lambda p, d, s: report)

    ats = client.post("/cv/master/compile", headers=AUTH).json()["ats"]
    assert ats["ok"] is False
    assert ats["findings"][0]["code"] == "email_missing"
    assert ats["findings"][0]["fix"]  # every finding says what to do about it


def test_compile_surfaces_latex_failure_as_422(client, monkeypatch):
    def boom(doc, scope, override=None):
        raise BuildError("! Undefined control sequence")

    monkeypatch.setattr("jobpilot.api.routes.cv.compile_document", boom)
    r = client.post("/cv/master/compile", headers=AUTH)
    assert r.status_code == 422
    assert "Undefined control sequence" in r.json()["detail"]


def test_pdf_served_after_compile(client, monkeypatch, tmp_path):
    pdf = tmp_path / "master" / "cv.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4\n%fake\n")
    monkeypatch.setattr("jobpilot.api.routes.cv.build_dir", lambda scope: tmp_path / scope)
    r = client.get("/cv/master/pdf", headers=AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


# --------------------------------------------------------------------------- #
# Raw LaTeX override
# --------------------------------------------------------------------------- #
def test_tex_starts_generated_and_is_not_an_override(client):
    r = client.get("/cv/master/tex", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["overridden"] is False
    assert "cv.tex" in body["files"]
    assert body["files"] == body["generated"]


def test_override_is_what_gets_built(client, monkeypatch):
    seen = {}

    class FakeResult:
        pages = 1
        pdf = None

    def fake_compile(doc, scope, override=None):
        seen["override"] = override
        return FakeResult()

    monkeypatch.setattr("jobpilot.api.routes.cv.compile_document", fake_compile)
    monkeypatch.setattr("jobpilot.api.routes.cv.check_build", lambda *a, **k: None)

    client.post("/cv/master/compile", headers=AUTH)
    assert seen["override"] is None

    r = client.put("/cv/master/tex", headers=AUTH, json={"files": {"cv.tex": "% mine\n"}})
    assert r.status_code == 200
    assert r.json()["overridden"] is True
    assert r.json()["files"]["cv.tex"] == "% mine\n"
    # …and the generated text is still reported, so the editor can offer a revert.
    assert r.json()["generated"]["cv.tex"] != "% mine\n"

    client.post("/cv/master/compile", headers=AUTH)
    assert seen["override"] == {"cv.tex": "% mine\n"}


def test_saving_the_document_keeps_the_override(client):
    """A JSON edit must not silently discard hand-written LaTeX."""
    client.put("/cv/master/tex", headers=AUTH, json={"files": {"cv.tex": "% mine\n"}})
    doc = _master(client)["document"]
    doc["header"]["position"] = "Backend Engineer"
    r = client.put("/cv/master", headers=AUTH, json=doc)
    assert r.status_code == 200
    assert r.json()["tex_override"] is True
    assert client.get("/cv/master/tex", headers=AUTH).json()["files"]["cv.tex"] == "% mine\n"


def test_override_is_cleared_only_on_request(client):
    client.put("/cv/master/tex", headers=AUTH, json={"files": {"cv.tex": "% mine\n"}})
    r = client.delete("/cv/master/tex", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["overridden"] is False
    assert r.json()["files"] == r.json()["generated"]
    assert _master(client)["tex_override"] is False


@pytest.mark.parametrize(
    "path", ["/etc/passwd.tex", "../escape.tex", "resume/../../out.tex", "cv.sh"]
)
def test_override_paths_that_escape_the_build_dir_are_refused(client, path):
    r = client.put("/cv/master/tex", headers=AUTH, json={"files": {path: "x"}})
    assert r.status_code == 422


def test_empty_files_is_not_a_silent_delete(client):
    client.put("/cv/master/tex", headers=AUTH, json={"files": {"cv.tex": "% mine\n"}})
    r = client.put("/cv/master/tex", headers=AUTH, json={"files": {}})
    assert r.status_code == 422
    assert client.get("/cv/master/tex", headers=AUTH).json()["overridden"] is True


def test_rollback_restores_the_latex_the_version_was_built_from(client):
    """Restoring v_n has to mean the PDF v_n produced, .tex included."""
    overridden = client.put(
        "/cv/master/tex", headers=AUTH, json={"files": {"cv.tex": "% mine\n"}}
    ).json()["version"]
    client.delete("/cv/master/tex", headers=AUTH)
    assert _master(client)["tex_override"] is False

    r = client.post(f"/cv/master/rollback/{overridden}", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["tex_override"] is True
    assert client.get("/cv/master/tex", headers=AUTH).json()["files"]["cv.tex"] == "% mine\n"
