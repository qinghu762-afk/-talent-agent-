from datetime import timedelta

from test_business import data, login
from test_worker import invoke


def test_assessment_list_never_leaks_published_answers(client):
    login(client)
    talent = data(client.post("/api/v1/talents", json={"profile": {"name": "合成"}}), 201)
    data(client.post("/api/v1/users", json={"username": "employee", "password": "Employee123!", "role": "employee", "talent_id": talent["id"]}), 201)
    q = data(client.post("/api/v1/questions", json={"title": "合成", "question_type": "single", "answer": "secret-correct-answer", "points": 1}), 201)
    exam = data(client.post("/api/v1/assessments", json={"title": "合成测评", "talent_id": talent["id"], "question_ids": [q["id"]]}), 201)
    approval = data(client.post(f"/api/v1/assessments/{exam['id']}/publish"), 201)
    data(client.post(f"/api/v1/approvals/{approval['id']}/resolve", json={"approved": True}))
    client.post("/api/v1/auth/logout")
    login(client, "employee", "Employee123!")
    assert "secret-correct-answer" not in client.get("/api/v1/assessments").text
    assert "secret-correct-answer" not in client.get(f"/api/v1/assessments/{exam['id']}").text
    assert client.get("/api/v1/questions/" + q["id"]).status_code == 403
    assert client.patch(f"/api/v1/assessments/{exam['id']}", json={"status": "rated"}).status_code == 403


def test_expired_lease_resumes_and_sse_reconnect_uses_sequence(client):
    login(client)
    from talent_platform.db import Run, now
    from talent_platform.worker import Worker
    run = data(client.post("/api/v1/jobs/parse", json={"description": "Python开发", "title": "研发"}), 202)
    async def expire():
        async with client.app.state.stores.facts() as db:
            row = await db.get(Run, run["id"])
            row.status = "running"
            row.lease_until = now() - timedelta(seconds=1)
            await db.commit()
    invoke(client, expire)
    async def model(kind, payload, run_id, actor):
        return {"requirements": {"required_skills": ["Python"]}, "versions": {"model": "test-only"}}
    worker = Worker(client.app.state.config, client.app.state.stores, model)
    assert invoke(client, worker.run_once, run["id"])
    assert data(client.get("/api/v1/runs/" + run["id"]))["status"] == "succeeded"
    events = client.get(f"/api/v1/runs/{run['id']}/events", headers={"Last-Event-ID": "1"})
    assert events.status_code == 200 and "id: 1\n" not in events.text and "succeeded" in events.text
    assert not invoke(client, worker.run_once, run["id"])
    assert data(client.get("/api/v1/jobs"))["total"] == 1


def test_dify_tool_requires_explicit_registration_and_no_actor_injection(client):
    login(client)
    skill = data(client.post("/api/v1/skills", json={"name": "解析", "version": "1", "handler": "job", "enabled": True, "input_schema": {"type": "object"}}), 201)
    endpoint = "/api/v1/integrations/dify/skills/execute"
    assert client.post(endpoint, json={"skill_id": skill["id"]}).status_code == 401
    header = {"X-Service-Key": "test-service-private-key"}
    assert client.post(endpoint, json={"skill_id": skill["id"]}, headers=header).status_code == 404
    data(client.patch("/api/v1/skills/" + skill["id"], json={"config": {"allow_dify": True}}))
    assert client.post(endpoint, json={"skill_id": skill["id"], "org_id": "other"}, headers=header).status_code == 403
    result = data(client.post(endpoint, json={"skill_id": skill["id"], "parameters": {"description": "Python"}, "actor": {"role": "admin", "org_id": "other"}}, headers=header), 202)
    async def check():
        from talent_platform.db import Run
        async with client.app.state.stores.facts() as db:
            r = await db.get(Run, result["id"])
            assert r.actor["org_id"] == "default"
    invoke(client, check)


def test_batch_failure_isolation_children_durable(client):
    login(client)
    run = data(client.post("/api/v1/talents/import", files=[("files", ("good.txt", "合成".encode())), ("files", ("bad.pdf", b"broken"))]), 202)
    from talent_platform.worker import Worker
    worker = Worker(client.app.state.config, client.app.state.stores)
    invoke(client, worker.run_once, run["id"])
    result = data(client.get("/api/v1/runs/" + run["id"]))
    assert result["result"]["count"] == 2
    assert len({r["id"] for r in result["result"]["files"]}) == 2
