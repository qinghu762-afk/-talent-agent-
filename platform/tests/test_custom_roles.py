from test_business import data, login


def test_custom_role_restricts_operations_and_field_evidence(client):
    login(client)
    profile = {"name": "合成人才", "location": "合成地点", "skills": ["Python"], "summary": "合成地点的软件开发人才", "evidence": [{"field": "location", "value": "合成地点", "quote": "现居合成地点"}]}
    talent = data(client.post("/api/v1/talents", json={"profile": profile}), 201)
    role = data(client.post("/api/v1/roles", json={"name": "仅阅档案", "base_role": "hr", "permissions": ["GET:talents"], "denied_fields": ["location"], "data_scope": "org"}), 201)
    data(client.post("/api/v1/users", json={"username": "readonlyhr", "password": "Employee123!", "role_template_id": role["id"]}), 201)
    data(client.post("/api/v1/auth/logout"))
    login(client, "readonlyhr", "Employee123!")
    response = client.get("/api/v1/talents/" + talent["id"])
    assert response.status_code == 200 and "合成地点" not in response.text
    assert client.post("/api/v1/talents/text", json={"text": "合成简历"}).status_code == 403
    assert client.get("/api/v1/jobs").status_code == 403
