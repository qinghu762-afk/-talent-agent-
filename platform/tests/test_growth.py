from test_business import data, login


def setup_learning(client):
    login(client)
    talent = data(client.post("/api/v1/talents", json={"profile": {"name": "合成员工", "skills": ["Python"]}}), 201)
    course = data(client.post("/api/v1/courses", json={"title": "合成Python基础课", "content": "仅用于开发验收的合成课程", "duration_seconds": 10, "skills": ["Python"], "quiz": [{"id": "q", "title": "Python类型", "question_type": "single", "options": ["A", "B"], "answer": "A", "points": 100}]}), 201)
    plan = data(client.post("/api/v1/training-plans", json={"title": "合成培训", "talent_id": talent["id"], "course_ids": [course["id"]]}), 201)
    return talent, course, plan


def test_learning_progress_quiz_retake_and_growth_ledger(client):
    talent, course, plan = setup_learning(client)
    path = f"/api/v1/training-plans/{plan['id']}"
    assert client.post(path + "/quiz", json={"course_id": course["id"], "answers": {"q": "A"}}).status_code == 409
    progress = data(client.post(path + "/progress", json={"course_id": course["id"], "position_seconds": 10}))
    assert progress["status"] == "completed"
    failed = data(client.post(path + "/quiz", json={"course_id": course["id"], "answers": {"q": "B"}}))
    assert failed["score"] == 0 and not failed["passed"]
    passed = data(client.post(path + "/quiz", json={"course_id": course["id"], "answers": {"q": "A"}}))
    assert passed["score"] == 100 and passed["attempt"] == 2 and passed["passed"]
    growth = data(client.get(f"/api/v1/talents/{talent['id']}/growth"))
    assert len(growth["plans"]) == 1 and len(growth["events"]) == 3


def test_automatic_exam_composition_and_retest_require_approval(client):
    talent, _, _ = setup_learning(client)
    q = data(client.post("/api/v1/questions", json={"title": "合成题", "question_type": "single", "answer": "A", "points": 10, "skills": ["Python"]}), 201)
    exam = data(client.post("/api/v1/assessments/compose", json={"talent_id": talent["id"], "question_count": 1}), 201)
    assert exam["question_ids"] == [q["id"]] and exam["status"] == "draft"
    retest = data(client.post(f"/api/v1/assessments/{exam['id']}/retest"), 201)
    assert retest["parent_id"] == exam["id"] and retest["status"] == "draft"
    assert client.post(f"/api/v1/assessments/{retest['id']}/start").status_code == 409


def test_manual_verification_is_signed_by_server_and_deleted_rows_excluded(client):
    login(client)
    who = data(client.get("/api/v1/auth/me"))
    talent = data(client.post("/api/v1/talents", json={"profile": {"name": "合成", "source": "fake", "verified_by": "other"}}), 201)
    assert talent["profile"]["source"] == "manual" and talent["profile"]["verified_by"] == who["id"]
    data(client.delete("/api/v1/talents/" + talent["id"]))
    assert client.get("/api/v1/talents/" + talent["id"]).status_code == 404
    assert data(client.get("/api/v1/talents"))["total"] == 0
