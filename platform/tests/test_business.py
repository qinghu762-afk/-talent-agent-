
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYSQL_URL", "sqlite+aiosqlite:///" + str(tmp_path / "business.db"))
    monkeypatch.setenv("POSTGRES_URL", "sqlite+aiosqlite:///" + str(tmp_path / "analytics.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "files"))
    monkeypatch.setenv("JWT_SECRET", "test-isolated-platform-secret-at-least-32")
    monkeypatch.setenv("ADMIN_PASSWORD", "TestPlatform123!")
    monkeypatch.setenv("INTERNAL_SERVICE_KEY", "test-service-private-key")
    from talent_platform.config import settings
    settings.cache_clear()
    from talent_platform.api import create_app
    with TestClient(create_app()) as c:
        yield c
    settings.cache_clear()


def data(response, status=200):
    assert response.status_code == status, response.text
    result = response.json()
    assert result["code"] == "ok" and result["request_id"]
    return result["data"]


def login(client, username="admin", password="TestPlatform123!"):
    return data(client.post("/api/v1/auth/login", json={"username": username, "password": password}))


def test_auth_roles_and_original_files_are_private(client):
    assert client.get("/api/v1/talents").status_code == 401
    admin = login(client)
    assert admin["role"] == "admin"
    org = data(client.post("/api/v1/organizations", json={"name": "研发"}), 201)
    data(client.post("/api/v1/users", json={"username": "employee", "password": "Employee123!", "role": "employee", "org_id": org["id"]}), 201)
    client.post("/api/v1/auth/logout")
    login(client, "employee", "Employee123!")
    assert client.post("/api/v1/users", json={"username": "bad", "password": "Employee123!"}).status_code == 403
    assert client.get("/api/v1/users").status_code == 403
    assert client.get("/api/v1/documents/not-found/file").status_code == 404


def test_job_without_scoring_requirements_cannot_match(client):
    login(client)
    job = data(client.post("/api/v1/jobs", json={"title": "待补充", "description": "待补充", "requirements": {}}), 201)
    assert client.post(f"/api/v1/jobs/{job['id']}/match").status_code == 422


def test_assessment_approval_start_submit_and_employee_answer_redaction(client):
    login(client)
    talent = data(client.post("/api/v1/talents", json={"profile": {"name": "合成人才", "skills": ["Python"]}}), 201)
    data(client.post("/api/v1/users", json={"username": "candidate", "password": "Employee123!", "role": "employee", "talent_id": talent["id"]}), 201)
    question = data(client.post("/api/v1/questions", json={"title": "合成 Python 题", "question_type": "single", "options": ["A", "B"], "answer": "A", "points": 100, "skills": ["Python"]}), 201)
    exam = data(client.post("/api/v1/assessments", json={"title": "合成测评", "talent_id": talent["id"], "question_ids": [question["id"]], "duration_minutes": 30}), 201)
    assert client.post(f"/api/v1/assessments/{exam['id']}/start").status_code == 409
    approval = data(client.post(f"/api/v1/assessments/{exam['id']}/publish"), 201)
    data(client.post(f"/api/v1/approvals/{approval['id']}/resolve", json={"approved": True}))
    client.post("/api/v1/auth/logout")
    login(client, "candidate", "Employee123!")
    started = data(client.post(f"/api/v1/assessments/{exam['id']}/start"))
    assert "answer" not in started["questions"][0]
    assert "question_snapshot" not in started
    run = data(client.post(f"/api/v1/assessments/{exam['id']}/submit", json={"answers": {question["id"]: "A"}, "events": []}), 202)
    assert data(client.get(f"/api/v1/runs/{run['id']}"))["status"] == "queued"
    assert client.post(f"/api/v1/assessments/{exam['id']}/submit", json={"answers": {}}).status_code == 409


def test_org_and_field_permissions_are_enforced_before_data_return(client):
    login(client)
    org = data(client.post("/api/v1/organizations", json={"name": "另一部门"}), 201)
    talent = data(client.post("/api/v1/talents", json={"org_id": org["id"], "profile": {"name": "其他部门", "phone": "13800138000"}}), 201)
    data(client.post("/api/v1/users", json={"username": "hr1", "password": "Employee123!", "role": "hr"}), 201)
    client.post("/api/v1/auth/logout")
    login(client, "hr1", "Employee123!")
    assert client.get(f"/api/v1/talents/{talent['id']}").status_code == 404
    assert data(client.get("/api/v1/talents"))["total"] == 0


def test_task_cancel_and_cross_origin_csrf(client):
    login(client)
    assert client.post("/api/v1/talents/text", json={"text": "合成简历"}, headers={"Origin": "https://evil.invalid"}).status_code == 403
    task = data(client.post("/api/v1/talents/text", json={"text": "合成简历\n技能Python"}), 202)
    data(client.post(f"/api/v1/runs/{task['id']}/cancel"))
    assert data(client.get(f"/api/v1/runs/{task['id']}"))["status"] == "cancelled"


def test_zip_path_traversal_does_not_write_files(client, tmp_path):
    import io
    import zipfile
    login(client)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../escape.txt", "bad")
    response = client.post("/api/v1/talents/import", files={"files": ("bad.zip", stream.getvalue())})
    assert response.status_code == 422
    assert not (tmp_path / "escape.txt").exists()
