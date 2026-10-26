"""Restore a real backup into a NEW isolated Compose project; retain its stopped volumes.

Requires Windows PowerShell and prepared local images. Never restores over the source project.
"""
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

SNAPSHOT = '''import hashlib,json
from pathlib import Path
from sqlalchemy import select
from talent.db import Base,Document,Talent,session
result={"tables":{},"originals":{}}
with session() as db:
 for name,table in sorted(Base.metadata.tables.items()):
  if name in {"work","audit"}: continue
  rows=[]
  for row in db.execute(select(table).order_by(table.c.id)).mappings():
   item=dict(row)
   if name=="talents":
    item.pop("indexed_revision",None);item.pop("index_model",None)
   rows.append(item)
  payload=json.dumps(rows,sort_keys=True,ensure_ascii=False,default=str).encode()
  result["tables"][name]={"count":len(rows),"sha256":hashlib.sha256(payload).hexdigest()}
 for doc in db.scalars(select(Document)):
  actual=hashlib.sha256(Path(doc.path).read_bytes()).hexdigest()
  assert actual==doc.sha256
  result["originals"][doc.id]=actual
 result["pending_indexes"]=sum(t.active and t.indexed_revision!=t.revision for t in db.scalars(select(Talent)))
print(json.dumps(result,sort_keys=True))
'''


def main():
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    project = "talent-agent-recovery-" + stamp
    clone = root / ".tmp" / project
    clone.mkdir(parents=True, exist_ok=False)
    report = {"status": "running", "project": project, "port": 18081, "clone": str(clone),
              "scope": "new isolated project; source database and original files never replaced"}
    env = {k: v for k, v in os.environ.items() if k not in {"COMPOSE_FILE", "COMPOSE_PROJECT_NAME"}}

    def command(args, cwd=root, capture=False, input_text=None):
        return subprocess.run(args, cwd=cwd, env=env, check=True, text=True, encoding="utf-8",
                              capture_output=capture, input=input_text)

    def compose(*args, cwd=root, capture=False, input_text=None):
        return command(["docker", "compose", *args], cwd, capture, input_text)

    def snapshot(cwd):
        value = compose("exec", "-T", "api", "python", "-", cwd=cwd, capture=True, input_text=SNAPSHOT)
        return json.loads(value.stdout)

    def wait_idle(base):
        with httpx.Client(base_url=base + "/api/v1/", timeout=30, trust_env=False) as client:
            client.post("auth/login", json={"username": "admin", "password": os.environ["TALENT_ACCEPTANCE_PASSWORD"]}).raise_for_status()
            deadline = time.monotonic() + 1200
            while time.monotonic() < deadline:
                response = client.get("tasks")
                response.raise_for_status()
                if not any(t["status"] in {"queued", "dispatched", "running", "retry"} for t in response.json()):
                    return
                time.sleep(3)
            raise TimeoutError("Pending recovery work did not settle")

    try:
        # Only a brand-new project and unoccupied loopback port may be used.
        existing = command(["docker", "ps", "-a", "--filter", "label=com.docker.compose.project=" + project, "-q"], capture=True)
        if existing.stdout.strip():
            raise RuntimeError("Recovery project already exists")
        import socket
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 18081))
        wait_idle("http://127.0.0.1:18080")
        before = snapshot(root)
        command(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/backup.ps1"])
        archive = max((root / "backups").glob("talent-*.zip"), key=lambda p: p.stat().st_mtime)
        trusted = archive.with_suffix(".zip.sha256").read_text(encoding="ascii").strip()
        assert hashlib.sha256(archive.read_bytes()).hexdigest().upper() == trusted.upper()
        report.update(archive=str(archive), archive_sha256=trusted, before=before)
        text = (root / "compose.yaml").read_text(encoding="utf-8").replace("name: talent-agent\n", "name: " + project + "\n", 1)
        # Reuse only the prepared OCR model cache, read-only; all database/index volumes are fresh.
        text = text.replace('volumes: ["mineru-models:/models"]', 'volumes: ["mineru-models:/models:ro"]')
        text = text.replace("  mineru-models: {}", "  mineru-models: {external: true, name: talent-agent_mineru-models}")
        (clone / "compose.yaml").write_text(text, encoding="utf-8")
        shutil.copytree(root / "scripts", clone / "scripts")
        (clone / "infra").mkdir()
        shutil.copy2(root / "infra" / "ollama.conf", clone / "infra" / "ollama.conf")
        config = (root / ".env").read_text(encoding="utf-8")
        import re
        config = re.sub(r"(?m)^WEB_PORT=.*$", "WEB_PORT=18081", config)
        (clone / ".env").write_text(config, encoding="utf-8")
        (clone / "backups").mkdir()
        copied = clone / "backups" / archive.name
        shutil.copy2(archive, copied)
        command(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/restore.ps1",
                 "-Archive", str(copied), "-ExpectedSha256", trusted], cwd=clone)
        deadline = time.monotonic() + 180
        with httpx.Client(timeout=5, trust_env=False) as client:
            while time.monotonic() < deadline:
                try:
                    if client.get("http://127.0.0.1:18081/api/v1/health").is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(2)
            else:
                raise TimeoutError("Restored application health failed")
        wait_idle("http://127.0.0.1:18081")
        after = snapshot(clone)
        assert before["tables"] == after["tables"], "Restored facts, sources or historical results differ"
        assert before["originals"] == after["originals"], "Restored original hashes differ"
        assert after["pending_indexes"] == 0, "Restored indexes are not current"
        source_after = snapshot(root)
        assert source_after["tables"] == before["tables"] and source_after["originals"] == before["originals"]
        report.update(status="passed", after=after, source_unchanged=True,
                      checks=["verified archive SHA256", "real PostgreSQL restore", "all fact table fingerprints",
                              "all original file hashes", "rebuild current Milvus indexes", "source project unchanged"])
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        try:
            if (clone / "compose.yaml").exists():
                compose("stop", cwd=clone)
            report["recovery_containers_stopped"] = True
            report["recovery_volumes_retained"] = True
        finally:
            (root / "data" / "backup-restore-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({k: report.get(k) for k in ("status", "project", "archive", "source_unchanged")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
