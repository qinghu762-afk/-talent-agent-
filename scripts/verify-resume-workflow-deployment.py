"""Snapshot existing facts, then verify only synthetic imports on the chosen deployment."""
import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

SNAPSHOT = '''import hashlib,json
from pathlib import Path
from sqlalchemy import select
from talent.db import session,Talent,Document
def digest(value):
 return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
with session() as db:
 talents={t.id:digest([t.profile,t.revision,t.indexed_revision,t.index_model,t.active]) for t in db.scalars(select(Talent))}
 documents={}
 for d in db.scalars(select(Document)):
  original=hashlib.sha256(Path(d.path).read_bytes()).hexdigest()
  assert original==d.sha256
  documents[d.id]=digest([original,d.extracted,d.model_versions,d.talent_id])
print(json.dumps({'talents':talents,'documents':documents}))
'''


def snapshot():
    process = subprocess.run(["docker", "compose", "-p", "talent-agent", "exec", "-T", "api", "python", "-"],
                             input=SNAPSHOT, capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(process.stdout)


def verify(base_url, before):
    prefix = uuid4().hex[:10]
    source = ("SYNTHETIC TEST RESUME - NOT A REAL PERSON\n验收批次：" + prefix + "\n"
              "姓名：合成上线流程甲\n邮箱：deployment-" + prefix + "@example.invalid\n"
              "技能：Python、SQL\n教育经历：合成测试大学，本科，软件工程专业。\n")
    files = [("complete.txt", source), ("version-two.txt", source + "简历版本：第二版。\n"),
             ("partial.txt", "SYNTHETIC TEST RESUME - NOT A REAL PERSON\n验收批次：" + prefix + "\n技能：Python、SQL。")]
    with httpx.Client(base_url=base_url + "/api/v1/", trust_env=False, timeout=30) as client:
        def api(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        def wait(fetch):
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                result = fetch()
                if result:
                    return result
                time.sleep(2)
            raise TimeoutError("Synthetic workflow deployment task did not settle")

        api("POST", "auth/login", json={"username": "admin", "password": os.environ["TALENT_ACCEPTANCE_PASSWORD"]})
        batch = api("POST", "batches", files=[("files", (name, text.encode("utf-8"))) for name, text in files])
        def finished():
            value = api("GET", "batches/" + batch["id"])
            assert all(item["status"] != "failed" for item in value["items"])
            return value if all(item["status"] == "completed" for item in value["items"]) else None
        completed = wait(finished)
        items = {item["filename"]: item for item in completed["items"]}
        complete_id = items["complete.txt"]["talent_id"]
        assert items["version-two.txt"]["talent_id"] == complete_id
        partial_id = items["partial.txt"]["talent_id"]
        assert partial_id != complete_id
        def indexed(talent_id):
            value = api("GET", "talents/" + talent_id)
            return value if value["revision"] == value["indexed_revision"] else None
        complete = wait(lambda: indexed(complete_id))
        partial = wait(lambda: indexed(partial_id))
        assert len(complete["documents"]) == 2
        assert all(d["model_versions"]["resume_workflow"]["quality_status"] == "complete" for d in complete["documents"])
        report = partial["documents"][0]["model_versions"]["resume_workflow"]
        assert report["quality_status"] == "partial" and report["stop_reason"] == "no_progress"
        assert partial["profile"]["name"] is None and partial["profile"]["email"] is None
        assert any("核心信息" in issue for issue in partial["profile"]["anomalies"])
        reused = api("POST", "batches", files={"files": ("same-hash.txt", source.encode("utf-8"))})
        assert reused["items"][0]["reused"]
        after = snapshot()
        for key in ("talents", "documents"):
            assert all(after[key].get(identifier) == value for identifier, value in before[key].items())
        return {"status": "passed", "recorded_utc": datetime.now(timezone.utc).isoformat(),
                "scope": "real production ingestion, local Qwen, Postgres and Milvus; three synthetic files retained",
                "checks": ["report persisted", "partial indexed", "same-identity versions merged", "hash reuse",
                           "existing talent facts unchanged", "existing document metadata and original SHA256 unchanged"],
                "before_counts": {key: len(values) for key, values in before.items()},
                "after_counts": {key: len(values) for key, values in after.items()},
                "batch_id": batch["id"], "talent_ids": [complete_id, partial_id], "partial_report": report}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-only", action="store_true")
    parser.add_argument("--baseline", default=".tmp/resume-workflow-facts-before.json")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--output", default="data/resume-workflow-deployment.json")
    args = parser.parse_args()
    if args.snapshot_only:
        Path(args.baseline).write_text(json.dumps(snapshot()), encoding="utf-8")
        print("Read-only baseline saved")
        return 0
    try:
        report = verify(args.base_url, json.loads(Path(args.baseline).read_text(encoding="utf-8")))
    except Exception as exc:
        report = {"status": "failed", "error_type": type(exc).__name__}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Production workflow verification: " + report["status"])
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
