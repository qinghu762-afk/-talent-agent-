"""Real failure recovery checks, restricted to the talent-agent Compose project."""
import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx


def compose(*args, overlay=None):
    command = ["docker", "compose", "-p", "talent-agent", "-f", "compose.yaml"]
    if overlay:
        command += ["-f", str(overlay)]
    subprocess.run(command + list(args), check=True)


def main():
    password = os.environ["TALENT_ACCEPTANCE_PASSWORD"]
    root = Path(__file__).resolve().parents[1]
    stage = root / ".tmp" / "fault-verification"
    stage.mkdir(parents=True, exist_ok=True)
    server = stage / "server.py"
    server.write_text('''from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import time,urllib.request
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  data=urllib.request.urlopen('http://ollama:11434'+self.path,timeout=10).read()
  self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
 def do_POST(self):
  print('Delaying model POST for 10 seconds to trigger the 1-second client timeout',flush=True)
  self.rfile.read(int(self.headers.get('Content-Length','0')));time.sleep(10)
  self.send_response(200);self.end_headers()
ThreadingHTTPServer(('0.0.0.0',11434),Handler).serve_forever()
''', encoding="utf-8")
    overlay = stage / "compose.json"
    overlay.write_text(json.dumps({"services": {
        "worker": {"environment": {"OLLAMA_URL": "http://model-timeout:11434", "MODEL_TIMEOUT": "1"}},
        "model-timeout": {"image": "talent-agent-api:0.1.0", "command": ["python", "-u", "/fault/server.py"],
                          "volumes": [{"type": "bind", "source": server.as_posix(), "target": "/fault/server.py", "read_only": True}],
                          "networks": ["private"]}}}), encoding="utf-8")
    report = {"status": "running", "synthetic": True, "checks": []}
    try:
        with httpx.Client(base_url="http://127.0.0.1:18080/api/v1/", timeout=45, trust_env=False) as client:
            def api(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()

            def wait(fetch, timeout=900):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    value = fetch()
                    if value:
                        return value
                    time.sleep(2)
                raise TimeoutError("Recovery check timed out")

            def upload(label):
                tag = uuid4().hex[:8]
                text = (f"SYNTHETIC TEST DATA - NOT A REAL PERSON\nName: SYNTHETIC_{label}_{tag}\n"
                        f"Email: {label.lower()}{tag}@example.invalid\nSkills: Python\n"
                        "Company: SYNTHETIC LAB\nTitle: Python ENGINEER\nStart: 2020-01\nEnd: 2024-01\n")
                before = {t["id"] for t in api("GET", "tasks")}
                batch = api("POST", "batches", files={"files": ("synthetic-" + label + ".txt", text.encode())})
                batch["_previous_task_ids"] = before
                return batch

            def task_for(batch, kind, status):
                item = api("GET", "batches/" + batch["id"])["items"][0]
                subject = item.get("talent_id")
                tasks = api("GET", "tasks")
                if kind == "ingest":
                    return next((t for t in tasks if t["kind"] == kind and t["status"] == status
                                 and t["id"] not in batch["_previous_task_ids"]), None)
                return next((t for t in tasks if t["kind"] == kind and t["subject_id"] == subject and t["status"] == status), None)

            def indexed(batch):
                item = api("GET", "batches/" + batch["id"])["items"][0]
                if item["status"] == "failed":
                    raise AssertionError("Synthetic recovery document failed")
                if not item.get("talent_id"):
                    return None
                talent = api("GET", "talents/" + item["talent_id"])
                return talent if talent["indexed_revision"] == talent["revision"] and talent["index_model"] else None

            api("POST", "auth/login", json={"username": "admin", "password": password})
            wait(lambda: not any(t["status"] in {"queued", "dispatched", "running", "retry"} for t in api("GET", "tasks")))
            compose("stop", "-t", "60", "worker")
            queued = upload("RESTART")
            assert api("GET", "batches/" + queued["id"])["items"][0]["status"] == "queued"
            compose("up", "-d", "--no-deps", "--no-build", "--pull", "never", "worker")
            talent = wait(lambda: indexed(queued))
            report["checks"].append({"case": "worker restart with SQL-persisted pending work", "talent_id": talent["id"], "passed": True})
            compose("stop", "-t", "60", "worker")
            compose("up", "-d", "--no-deps", "--no-build", "--pull", "never", "model-timeout", "worker", overlay=overlay)
            timeout_batch = upload("TIMEOUT")
            retry = wait(lambda: task_for(timeout_batch, "ingest", "retry"), timeout=120)
            assert retry["attempts"] <= 4
            compose("up", "-d", "--no-deps", "--no-build", "--pull", "never", "worker")
            talent = wait(lambda: indexed(timeout_batch))
            report["checks"].append({"case": "real model HTTP read timeout then automatic retry", "task_id": retry["id"],
                                      "retry_observed": True, "talent_id": talent["id"], "passed": True})
            compose("stop", "model-timeout", overlay=overlay)
            compose("stop", "milvus")
            vector_batch = upload("VECTOR_OUTAGE")
            retry = wait(lambda: task_for(vector_batch, "index", "retry"), timeout=180)
            assert retry["attempts"] <= 4
            compose("up", "-d", "--no-deps", "--no-build", "--pull", "never", "milvus")
            talent = wait(lambda: indexed(vector_batch))
            report["checks"].append({"case": "Milvus outage preserves SQL profile and recovers indexing", "task_id": retry["id"],
                                      "talent_id": talent["id"], "passed": True})
            report["status"] = "passed"
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        try:
            compose("up", "-d", "--no-deps", "--no-build", "--pull", "never", "milvus", "worker")
            compose("stop", "model-timeout", overlay=overlay)
        finally:
            (root / "data" / "failure-recovery.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
