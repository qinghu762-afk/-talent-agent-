"""Record local image/model/lock digests without recording credentials or resume contents."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def main():
    root = Path(__file__).resolve().parents[1]
    images = sorted(set(command("docker", "compose", "--profile", "prepare", "config", "--images").splitlines()))
    records = []
    for name in images:
        details = json.loads(command("docker", "image", "inspect", name))[0]
        records.append({"name": name, "image_id": details["Id"], "repo_digests": details.get("RepoDigests", [])})
    script = '''import hashlib,json
from pathlib import Path
result=[]
for p in sorted(Path('/models').rglob('*')):
 if p.is_file() and '.locks' not in p.parts:
  h=hashlib.sha256()
  with p.open('rb') as f:
   for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
  result.append({'path':str(p.relative_to('/models')),'bytes':p.stat().st_size,'sha256':h.hexdigest()})
print(json.dumps(result))
'''
    model_hashes = json.loads(command("docker", "compose", "exec", "-T", "mineru", "python", "-c", script))
    with httpx.Client(timeout=10, trust_env=False) as client:
        response = client.get("http://127.0.0.1:11434/api/tags")
        response.raise_for_status()
        models = [{"name": m["name"], "digest": m["digest"], "bytes": m["size"]}
                  for m in response.json()["models"] if m["name"] in {"qwen3:4b", "bge-m3", "bge-m3:latest"}]
    paths = ["requirements.lock", "frontend/package-lock.json", "infra/mineru/requirements.lock",
             "Dockerfile", "infra/frontend.Dockerfile", "infra/mineru/Dockerfile", "infra/nginx.conf", "infra/ollama.conf", "compose.yaml"]
    locks = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths}
    output = {"recorded_utc": datetime.now(timezone.utc).isoformat(), "images": records, "models": models,
              "ocr_models": model_hashes, "locks_and_configuration": locks,
              "docker_memory_bytes": int(command("docker", "info", "--format", "{{.MemTotal}}")),
              "gpu": command("nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"),
              "notes": ["Local application image IDs are content hashes; preserve exported images for offline reproduction.",
                        "Only model/image metadata and dependency hashes are recorded; no credentials or resumes."]}
    target = root / "data" / "deployment-manifest.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Recorded {len(records)} images, {len(models)} Ollama models, {len(model_hashes)} OCR files: {target}")


if __name__ == "__main__":
    main()
