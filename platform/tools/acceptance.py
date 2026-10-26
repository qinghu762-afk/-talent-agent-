"""Real local stack acceptance using explicitly synthetic, isolated business data.

No container lifecycle or deletion operations. Credentials stay in memory. A state
file allows continuation after a corrected deployment; reports contain IDs and
measured checks, never passwords or complete resume text.
"""
import argparse
import asyncio
import hashlib
import io
import json
from pathlib import Path
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "verification"
BASE = "http://127.0.0.1:18080"
COMPLETE = "姓名：张合成\n电话：13800138000\n所在地：上海\n技能：Python、SQL\n教育：2020-09 至 2024-06，合成大学，本科。\n工作：2024-07 至 2025-07，合成科技，Python工程师。\n项目：数据分析平台，使用Python和SQL完成报表开发。"


class Acceptance:
    def __init__(self, state_filename='runtime-state.json'):
        self.config = dict(line.split("=", 1) for line in (ROOT / ".env").read_text("utf-8-sig").splitlines() if "=" in line and not line.startswith("#"))
        VERIFY.mkdir(exist_ok=True)
        self.path = VERIFY / state_filename
        self.state = json.loads(self.path.read_text("utf-8")) if self.path.exists() else {"synthetic": True, "id": uuid.uuid4().hex[:10], "checks": {}}
        self.clients = {}

    def save(self):
        self.path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def password(self, role):
        return hashlib.sha256((self.config["ADMIN_PASSWORD"] + self.state["id"] + role).encode()).hexdigest()

    async def call(self, role, method, path, expected=200, **kwargs):
        response = await self.clients[role].request(method, "/api/v1" + path, **kwargs)
        if response.status_code != expected:
            try:
                message = response.json().get("message", "")
            except ValueError:
                message = "non-JSON response"
            raise AssertionError(f"{method} {path}: HTTP {response.status_code}, expected {expected}; {message[:200]}")
        if "application/json" not in response.headers.get("content-type", ""):
            return response
        return response.json()["data"]

    async def login(self, role):
        self.clients[role] = httpx.AsyncClient(base_url=BASE, timeout=90, trust_env=False, headers={"Origin": BASE})
        username = "admin" if role == "admin" else "synthetic-" + self.state["id"] + "-" + role
        password = self.config["ADMIN_PASSWORD"] if role == "admin" else self.password(role)
        return await self.call(role, "POST", "/auth/login", json={"username": username, "password": password})

    async def setup(self):
        await self.login("admin")
        if not self.state.get("org_id"):
            org = await self.call("admin", "POST", "/organizations", 201, json={"name": "合成验收专用组织 " + self.state["id"], "synthetic": True})
            self.state["org_id"] = org["id"]
            self.save()
        for role in ("hr", "manager"):
            if not self.state.get(role + "_id"):
                user = await self.call("admin", "POST", "/users", 201, json={"username": "synthetic-" + self.state["id"] + "-" + role, "password": self.password(role), "role": role, "org_id": self.state["org_id"]})
                self.state[role + "_id"] = user["id"]
                self.save()
            await self.login(role)

    async def wait(self, role, ident, timeout=600):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            run = await self.call(role, "GET", "/runs/" + ident)
            if run["status"] != last:
                print(json.dumps({"run": ident, "kind": run["kind"], "status": run["status"], "attempt": run.get("attempt")}), flush=True)
                last = run["status"]
            if run["status"] in {"succeeded", "waiting_approval"}:
                return run
            if run["status"] in {"failed", "cancelled"}:
                raise AssertionError(f"{run['kind']} failed: {run.get('error')}")
            await asyncio.sleep(3)
        raise AssertionError(f"Task did not settle within {timeout}s: {ident}")

    async def step(self, name, action):
        if self.state["checks"].get(name, {}).get("passed"):
            return
        started = time.monotonic()
        try:
            detail = await action()
        except Exception as exc:
            self.state["checks"][name] = {"passed": False, "seconds": round(time.monotonic() - started, 3), "error": str(exc)[:500]}
            self.save()
            raise
        self.state["checks"][name] = {"passed": True, "seconds": round(time.monotonic() - started, 3), "detail": detail}
        self.save()
        print(json.dumps({"check": name, **self.state["checks"][name]}, ensure_ascii=False), flush=True)

    async def resume(self):
        if self.state.get("resume_run"):
            previous = await self.call("hr", "GET", "/runs/" + self.state["resume_run"])
            if previous["status"] in {"failed", "cancelled"}:
                self.state.setdefault("previous_failed_runs", []).append({"id": previous["id"], "kind": previous["kind"], "error": previous["error"]})
                self.state.pop("resume_run")
        if not self.state.get("resume_run"):
            created = await self.call("hr", "POST", "/talents/text", 202, json={"text": COMPLETE})
            self.state["resume_run"] = created["id"]
            self.save()
        run = await self.wait("hr", self.state["resume_run"])
        result = run["result"]
        assert result["report"]["quality_status"] == "complete", result["report"]
        self.state["talent_id"] = result["talent_id"]
        self.state["document_id"] = result["document_id"]
        self.save()
        talent = await self.call("hr", "GET", "/talents/" + result["talent_id"])
        assert talent["profile"]["name"] == "张合成"
        assert set(talent["profile"]["skills"]) >= {"Python", "SQL"}
        assert all(e.get("quote") in COMPLETE for e in talent["profile"]["evidence"])
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            talent = await self.call("hr", "GET", "/talents/" + result["talent_id"])
            if talent["indexed_revision"] == talent["revision"]:
                break
            await asyncio.sleep(3)
        assert talent["indexed_revision"] == talent["revision"], "Milvus index has not caught up"
        original = await self.call("hr", "GET", "/documents/" + result["document_id"] + "/file")
        assert original.content.decode() == COMPLETE
        return {"talent_id": result["talent_id"], "quality_status": result["report"]["quality_status"], "retry_count": result["report"]["retry_count"], "indexed_revision": talent["indexed_revision"], "versions": result["report"]["versions"]}

    async def partial_and_reuse(self):
        text = "姓名：李合成\n技能：Python"
        first = await self.call("hr", "POST", "/talents/text", 202, json={"text": text})
        outcome = (await self.wait("hr", first["id"]))["result"]
        assert outcome["report"]["quality_status"] == "partial"
        assert set(outcome["report"]["missing_fields"]) == {"contact", "education_or_experiences"}
        repeat = await self.call("hr", "POST", "/talents/text", 202, json={"text": text})
        cached = (await self.wait("hr", repeat["id"]))["result"]
        assert cached["reused"] and cached["talent_id"] == outcome["talent_id"]
        assert cached["document_id"] == outcome["document_id"]
        self.state["partial_talent_id"] = outcome["talent_id"]
        return {"partial_saved": True, "missing_fields": outcome["report"]["missing_fields"], "same_hash_reused": True}

    async def merge_undo(self):
        newer = COMPLETE + "\n证书：合成SQL课程结业证。"
        created = await self.call("hr", "POST", "/talents/text", 202, json={"text": newer})
        result = (await self.wait("hr", created["id"]))["result"]
        assert result["talent_id"] == self.state["talent_id"] and result["merge_id"]
        undone = await self.call("hr", "POST", "/merges/" + result["merge_id"] + "/undo")
        assert undone
        return {"identity_merged": True, "merge_id": result["merge_id"], "undo": undone}

    async def matching(self):
        # Job parsing uses real Qwen; the HR edits below are an explicitly supported path.
        created = await self.call("hr", "POST", "/jobs/parse", 202, json={"title": "合成Python工程师", "description": "必须掌握Python。优先掌握SQL。职责：使用Python开发数据分析平台。"})
        parsed = (await self.wait("hr", created["id"]))["result"]
        self.state["job_id"] = parsed["job_id"]
        assert "Python" in parsed["requirements"]["required_skills"]
        await self.call("hr", "PATCH", "/jobs/" + parsed["job_id"], json={"requirements": {"required_skills": ["Python"], "preferred_skills": ["SQL"], "min_education": "本科", "min_experience_months": 6, "responsibilities": ["数据分析平台"]}})
        created = await self.call("hr", "POST", "/jobs/" + parsed["job_id"] + "/match", 202)
        matched = await self.wait("hr", created["id"])
        candidates = matched["result"]["candidates"]
        assert candidates and all(c["score"]["eligible"] for c in candidates)
        assert self.state["partial_talent_id"] not in {c["talent_id"] for c in candidates}
        for c in candidates:
            dims = c["score"]["dimensions"]
            active = [d for d in dims.values() if d.get("score") is not None]
            if active:
                score = sum(d["score"] * d["weight"] for d in active) / sum(d["weight"] for d in active)
                assert abs(score - c["score"]["total"]) <= .02
        csv = await self.call("hr", "GET", "/matches/" + created["id"] + "/export.csv")
        assert b"\xef\xbb\xbf" in csv.content[:3]
        self.state["match_run"] = created["id"]
        return {"candidate_count": len(candidates), "partial_filtered": True, "top_score": candidates[0]["score"]["total"], "csv_bytes": len(csv.content)}

    async def knowledge(self):
        doc = await self.call("hr", "POST", "/knowledge/text", 201, json={"title": "合成验收学习制度", "text": "本制度为合成测试资料。员工每季度至少完成两门Python培训课程。培训考核通过分数为80分。", "scope": "org"})
        await self.wait("hr", doc["run_id"])
        created = await self.call("hr", "POST", "/chat", 202, json={"question": "根据合成验收学习制度，员工每季度需要完成几门培训课程？"})
        result = (await self.wait("hr", created["id"]))["result"]
        assert result["citations"], result
        assert all(c["quote"] in doc["text"] for c in result["citations"] if c["source_id"] == doc["id"])
        assert any(c["source_id"] == doc["id"] for c in result["citations"])
        self.state["knowledge_id"] = doc["id"]
        return {"source_id": doc["id"], "citations": len(result["citations"])}

    async def assessment_training(self):
        talent_id = self.state["talent_id"]
        if not self.state.get("employee_id"):
            user = await self.call("admin", "POST", "/users", 201, json={"username": "synthetic-" + self.state["id"] + "-employee", "password": self.password("employee"), "role": "employee", "org_id": self.state["org_id"], "talent_id": talent_id})
            self.state["employee_id"] = user["id"]
            self.save()
        await self.login("employee")
        await self.call("employee", "GET", "/questions", 403)
        course = await self.call("hr", "POST", "/courses", 201, json={"title": "合成Python基础课程", "content": "合成课程：Python使用def定义函数。", "skills": ["Python"], "duration_seconds": 10, "quiz": [{"id": "synthetic-q", "title": "定义函数的关键字", "question_type": "single", "options": ["def", "class"], "answer": "def", "points": 1}]})
        question = await self.call("hr", "POST", "/questions", 201, json={"title": "合成Python基础题", "question_type": "single", "options": ["def", "class"], "answer": "def", "skills": ["Python"], "points": 10})
        exam = await self.call("hr", "POST", "/assessments", 201, json={"title": "合成岗位测评", "talent_id": talent_id, "question_ids": [question["id"]], "duration_minutes": 10})
        approval = await self.call("hr", "POST", "/assessments/" + exam["id"] + "/publish", 201)
        await self.call("manager", "POST", "/approvals/" + approval["id"] + "/resolve", json={"approved": True, "comment": "合成验收批准"})
        started = await self.call("employee", "POST", "/assessments/" + exam["id"] + "/start")
        assert "answer" not in started["questions"][0]
        submitted = await self.call("employee", "POST", "/assessments/" + exam["id"] + "/submit", 202, json={"answers": {question["id"]: "class"}, "events": [{"type": "blur", "at": "synthetic"}]})
        result = (await self.wait("employee", submitted["id"]))["result"]
        assert result["total"] == 0
        await self.call("manager", "POST", "/approvals/" + result["approval_id"] + "/resolve", json={"approved": True, "comment": "合成评分可复算"})
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            plans = (await self.call("hr", "GET", "/training-plans"))["items"]
            plan = next((p for p in plans if p.get("baseline_assessment_id") == exam["id"]), None)
            if plan:
                break
            await asyncio.sleep(3)
        assert plan and plan.get('title') and plan.get('course_ids'), "Automatic training did not produce an authorized course"
        selected = await self.call('hr', 'GET', '/courses/' + plan['course_ids'][0])
        assert 'Python' in selected['skills'] and selected['org_id'] == self.state['org_id']
        assert plan['reasons'].get(selected['id']), 'Selected course requires a reason'
        course = selected
        progress = await self.call("employee", "POST", "/training-plans/" + plan["id"] + "/progress", json={"course_id": course["id"], "position_seconds": 10})
        assert progress["progress"][course["id"]]["completed"]
        quiz = await self.call("employee", "POST", "/training-plans/" + plan["id"] + "/quiz", json={"course_id": course["id"], "answers": {"synthetic-q": "def"}})
        assert quiz["score"] == 100 and quiz["passed"]
        retest = await self.call("hr", "POST", "/assessments/" + exam["id"] + "/retest", 201)
        growth = await self.call("employee", "GET", "/talents/" + talent_id + "/growth")
        assert growth["events"] and len(growth["assessments"]) >= 2
        return {"objective_score": result["total"], "approval_restored": True, "automatic_training": True, "quiz_score": quiz["score"], "retest_id": retest["id"], "growth_events": len(growth["events"])}

    async def analysis(self):
        results = {}
        for datasource, question in [("postgres", "按所在地统计本组织人才数量，返回location和count，生成柱状图。"), ("mysql", "统计本组织岗位数量，返回job_count。")]:
            created = await self.call("manager", "POST", "/analysis", 202, json={"question": question, "datasource": datasource})
            result = (await self.wait("manager", created["id"]))["result"]
            assert not result.get("needs_clarification"), result
            assert result["rows"] and result["report_id"]
            assert "org_id" in result["sql"]
            sizes = {}
            for fmt in ("docx", "pdf"):
                document = await self.call("manager", "GET", "/reports/" + result["report_id"] + "/export?format=" + fmt)
                assert document.content.startswith(b"PK" if fmt == "docx" else b"%PDF")
                (VERIFY / ("real-report-" + datasource + "." + fmt)).write_bytes(document.content)
                sizes[fmt] = len(document.content)
            results[datasource] = {"rows": len(result["rows"]), "report_id": result["report_id"], "export_bytes": sizes}
        return results

    async def run(self, only):
        try:
            await self.setup()
            actions = {"resume": self.resume, "partial_and_reuse": self.partial_and_reuse, "merge_undo": self.merge_undo, "matching": self.matching, "knowledge": self.knowledge, "assessment_training": self.assessment_training, "analysis": self.analysis}
            for name, action in actions.items():
                if only and name not in only:
                    continue
                await self.step(name, action)
        finally:
            for client in self.clients.values():
                await client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    asyncio.run(Acceptance().run(args.only))
