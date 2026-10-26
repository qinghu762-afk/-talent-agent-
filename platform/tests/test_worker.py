
from test_business import data, login


def invoke(client, method, *args):
    return client.portal.call(method, *args)


def test_hash_reuse_identity_merge_and_undo(client):
    login(client)
    from talent_platform.persistence import persist_resume, undo_merge
    stores = client.app.state.stores
    who = data(client.get("/api/v1/auth/me"))
    profile = {"name": "张合成", "phone": "13800138000", "skills": ["Python"], "education": [], "experiences": []}
    report = {"quality_status": "partial", "missing_fields": ["education_or_experience"], "retry_count": 1}
    first = invoke(client, persist_resume, stores, who, {"sha256": "a" * 64, "filename": "a.txt", "path": "a"}, {"profile": profile, "report": report})
    cached = invoke(client, persist_resume, stores, who, {"sha256": "a" * 64, "filename": "a.txt", "path": "a"}, {"profile": {}, "report": {}})
    assert cached["talent_id"] == first["talent_id"] and cached["reused"]
    second = invoke(client, persist_resume, stores, who, {"sha256": "b" * 64, "filename": "b.txt", "path": "b"}, {"profile": {**profile, "skills": ["SQL"]}, "report": report})
    assert second["talent_id"] == first["talent_id"] and second["merge_id"]
    detail = data(client.get("/api/v1/talents/" + first["talent_id"]))
    assert set(detail["profile"]["skills"]) == {"Python", "SQL"}
    assert detail["documents"][0]["model_versions"]["resume_workflow"]["quality_status"] == "partial"
    invoke(client, undo_merge, stores, who, second["merge_id"])
    detail = data(client.get("/api/v1/talents/" + first["talent_id"]))
    assert detail["profile"]["skills"] == ["Python"]
    assert len(data(client.get("/api/v1/talents"))["items"]) == 2


def test_worker_runs_scoring_to_approval_and_persists_answers(client):
    login(client)
    talent = data(client.post("/api/v1/talents", json={"profile": {"name": "合成"}}), 201)
    q = data(client.post("/api/v1/questions", json={"title": "单选", "question_type": "single", "options": ["A", "B"], "answer": "A", "points": 100}), 201)
    exam = data(client.post("/api/v1/assessments", json={"title": "测试", "talent_id": talent["id"], "question_ids": [q["id"]]}), 201)
    approval = data(client.post(f"/api/v1/assessments/{exam['id']}/publish"), 201)
    data(client.post(f"/api/v1/approvals/{approval['id']}/resolve", json={"approved": True}))
    data(client.post(f"/api/v1/assessments/{exam['id']}/start"))
    run = data(client.post(f"/api/v1/assessments/{exam['id']}/submit", json={"answers": {q["id"]: "A"}}), 202)
    from talent_platform.worker import Worker
    async def scorer(kind, payload, run_id, actor):
        assert kind == "assessment" and payload["answers"][q["id"]] == "A"
        return {"total": 100, "dimensions": {"Python": 100}, "risks": [], "inference": True}
    worker = Worker(client.app.state.config, stores=client.app.state.stores, executor=scorer)
    invoke(client, worker.run_once, run["id"])
    result = data(client.get("/api/v1/runs/" + run["id"]))
    assert result["status"] == "waiting_approval" and result["result"]["total"] == 100
    approvals = data(client.get("/api/v1/approvals"))["items"]
    rating = next(x for x in approvals if x.get("kind") == "assessment_rating")
    data(client.post(f"/api/v1/approvals/{rating['id']}/resolve", json={"approved": True}))
    assert data(client.get("/api/v1/runs/" + run["id"]))["status"] == "succeeded"


def test_cancelled_task_does_not_execute(client):
    login(client)
    run = data(client.post("/api/v1/talents/text", json={"text": "合成简历"}), 202)
    data(client.post(f"/api/v1/runs/{run['id']}/cancel"))
    from talent_platform.worker import Worker
    async def never(*args):
        raise AssertionError("cancelled task executed")
    worker = Worker(client.app.state.config, stores=client.app.state.stores, executor=never)
    assert not invoke(client, worker.run_once, run["id"])
