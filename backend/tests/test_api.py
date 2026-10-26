
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from talent import db as database
from talent.config import settings
from talent.db import Base, Document, Work


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "files"))
    monkeypatch.setenv("JWT_SECRET", "test-secret-32-bytes-long-at-least-12345")
    monkeypatch.setenv("ADMIN_PASSWORD", "TestPassword123!")
    settings.cache_clear()
    database._engine = database.make_engine(settings().database_url)
    Base.metadata.create_all(database._engine)
    from talent.api import app
    with TestClient(app) as c:
        yield c
    database._engine.dispose()
    database._engine = None
    settings.cache_clear()


def login(client):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "TestPassword123!"})
    assert response.status_code == 200, response.text


def test_private_files_and_talents_require_login(client):
    assert client.get("/api/v1/talents").status_code == 401
    assert client.get("/api/v1/documents/anything/file").status_code == 401


def test_upload_reuses_hash_and_keeps_individual_errors(client):
    login(client)
    response = client.post("/api/v1/batches", files=[("files", ("a.txt", b"hello")), ("files", ("bad.exe", b"bad"))])
    assert response.status_code == 201, response.text
    items = response.json()["items"]
    assert items[1]["status"] == "failed"
    again = client.post("/api/v1/batches", files={"files": ("copy.txt", b"hello")})
    assert again.json()["items"][0]["reused"]
    with database.session() as db:
        assert len(db.scalars(select(Document)).all()) == 1
        assert len(db.scalars(select(Work).where(Work.kind == "ingest")).all()) == 1


def test_recruiter_cannot_manage_accounts(client):
    login(client)
    response = client.post("/api/v1/users", json={"username": "hr", "password": "RecruiterPass123", "role": "recruiter"})
    assert response.status_code == 201
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"username": "hr", "password": "RecruiterPass123"})
    assert client.get("/api/v1/users").status_code == 403
    assert client.get("/api/v1/dashboard").status_code == 200


def test_cross_origin_cookie_mutation_rejected(client):
    login(client)
    response = client.post("/api/v1/jobs", json={"title": "x", "description": "Python"}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_job_edit_optimistic_lock_and_match_snapshot(client):
    login(client)
    job = client.post("/api/v1/jobs", json={"title": "工程师", "description": "必须熟练Python"}).json()
    edited = client.put(f"/api/v1/jobs/{job['id']}", json={"title": "工程师", "revision": 1,
                        "requirements": {"required_skills": ["Python"]}})
    assert edited.status_code == 200, edited.text
    stale = client.put(f"/api/v1/jobs/{job['id']}", json={"title": "old", "revision": 1, "requirements": {}})
    assert stale.status_code == 409
    run = client.post(f"/api/v1/jobs/{job['id']}/matches")
    assert run.status_code == 202, run.text
    snapshot = client.get(f"/api/v1/matches/{run.json()['id']}").json()
    assert snapshot["job_snapshot"]["requirements"]["required_skills"] == ["Python"]


def test_login_throttled_after_repeated_failures(client):
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "bad"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "bad"}).status_code == 429


def test_password_change_revokes_previous_session(client):
    login(client)
    user = client.get("/api/v1/auth/me").json()
    result = client.put(f"/api/v1/users/{user['id']}", json={"password": "ChangedPassword123!"})
    assert result.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_manual_correction_refreshes_portrait_and_drops_obsolete_source_claims(client):
    from talent.db import Talent
    from talent.schemas import Evidence, TalentProfile
    login(client)
    original = TalentProfile(name="张三", skills=["Python"], summary="Python画像", tags=["Python"],
                             evidence={"skills.0": [Evidence(quote="Python", source_id="old-source")]})
    with database.session() as db:
        talent = Talent(name="张三", profile=original.model_dump())
        db.add(talent)
        db.flush()
        talent_id = talent.id
    edited = original.model_copy(update={"skills": ["Java"]})
    result = client.put(f"/api/v1/talents/{talent_id}", json={"profile": edited.model_dump(), "revision": 1})
    assert result.status_code == 200
    profile = result.json()["profile"]
    assert "Java" in profile["summary"] and "Python" not in profile["summary"]
    assert "Java" in profile["tags"] and "Python" not in profile["tags"]
    assert "skills.0" not in profile["evidence"]


def test_csv_export_neutralizes_formulas_after_leading_whitespace():
    from talent.api import csv_safe
    assert csv_safe("  =1+1").startswith("'")

