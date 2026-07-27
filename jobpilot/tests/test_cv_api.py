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
    assert body["document"]["header"]["first_name"] == "KHOI"
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

    rows = client.get("/cv/master/versions", headers=AUTH).json()
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


def test_pdf_404_before_compile(client, monkeypatch, tmp_path):
    monkeypatch.setattr("jobpilot.api.routes.cv.build_dir", lambda scope: tmp_path / scope)
    assert client.get("/cv/master/pdf", headers=AUTH).status_code == 404


def test_compile_returns_page_count(client, monkeypatch):
    class FakeResult:
        pages = 1

    monkeypatch.setattr("jobpilot.api.routes.cv.compile_document", lambda doc, scope: FakeResult())
    r = client.post("/cv/master/compile", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"scope": "master", "version": 1, "pages": 1, "pdf_url": "/cv/master/pdf"}


def test_compile_surfaces_latex_failure_as_422(client, monkeypatch):
    def boom(doc, scope):
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
