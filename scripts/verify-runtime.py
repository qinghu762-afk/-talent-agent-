"""Explicit real-service checks; writes synthetic records to the selected deployment."""
import argparse
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx


def run(base_url, password, output):
    started = time.monotonic()
    prefix = "SYNTHETIC_RUNTIME_" + uuid4().hex[:8].upper()
    source = (f"SYNTHETIC TEST DATA - NOT A REAL PERSON\nName: {prefix}\n"
              f"Email: {prefix.lower()}@example.invalid\nLocation: SHANGHAI\nSkills: Python\n"
              "Company: SYNTHETIC LAB\nTitle: Python ENGINEER\nStart: 2020-01\nEnd: 2024-01\n")
    with httpx.Client(base_url=base_url.rstrip("/") + "/api/v1/", timeout=90, trust_env=False) as client:
        def api(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        def wait(fetch, limit=900):
            deadline = time.monotonic() + limit
            while time.monotonic() < deadline:
                value = fetch()
                if value:
                    return value
                time.sleep(2)
            raise TimeoutError("Synthetic runtime check timed out")

        def completed_batch(batch_id):
            value = api("GET", "batches/" + batch_id)
            if any(i["status"] == "failed" for i in value["items"]):
                raise AssertionError("Synthetic batch contains failed documents")
            return value if all(i["status"] == "completed" for i in value["items"]) else None

        def indexed(talent_id):
            value = api("GET", "talents/" + talent_id)
            return value if value["revision"] == value["indexed_revision"] and value["index_model"] else None

        api("POST", "auth/login", json={"username": "admin", "password": password})
        payload = source.encode()
        batch = api("POST", "batches", files=[("files", (f"synthetic-runtime-{i:03}.txt", payload)) for i in range(200)])
        assert len(batch["items"]) == 200
        assert sum(not i["reused"] for i in batch["items"]) == 1
        print("200-file batch accepted with one source-hash task", flush=True)
        rejected = client.post("batches", files=[("files", (f"overflow-{i}.txt", payload)) for i in range(201)])
        assert rejected.status_code in {400, 413, 422}

        def upload_again(number):
            with httpx.Client(base_url=str(client.base_url), cookies=client.cookies, trust_env=False, timeout=90) as parallel:
                response = parallel.post("batches", files={"files": (f"concurrent-{number}.txt", payload)})
                response.raise_for_status()
                item = response.json()["items"][0]
                assert item["reused"]
                return response.json()["id"]

        with ThreadPoolExecutor(max_workers=8) as pool:
            concurrent_batches = list(pool.map(upload_again, range(8)))
        done = wait(lambda: completed_batch(batch["id"]))
        ids = {i["talent_id"] for i in done["items"]}
        assert len(ids) == 1
        talent_id = ids.pop()
        original = wait(lambda: indexed(talent_id))
        assert original["profile"]["name"] == prefix
        assert len(original["documents"]) == 1

        version = api("POST", "batches", files={"files": ("synthetic-runtime-version.txt", (source + "Certificate: PMP\n").encode())})
        version = wait(lambda: completed_batch(version["id"]))
        assert version["items"][0]["talent_id"] == talent_id
        merged = wait(lambda: indexed(talent_id))
        assert len(merged["documents"]) == 2 and len(merged["merges"]) == 1
        assert merged["revision"] > original["revision"]
        assert "PMP" in merged["profile"]["certificates"]
        print("Same identity merged with original sources and revision history", flush=True)

        separate_source = source.replace(prefix.lower() + "@example.invalid", "different-" + prefix.lower() + "@example.invalid")
        separate = api("POST", "batches", files={"files": ("synthetic-runtime-conflict.txt", separate_source.encode())})
        separate = wait(lambda: completed_batch(separate["id"]))
        separate_id = separate["items"][0]["talent_id"]
        assert separate_id != talent_id
        wait(lambda: indexed(separate_id))
        issues = api("GET", "issues")
        assert any(i["kind"] == "identity_conflict" and separate_id in {i["talent_id"], i.get("other_id")} for i in issues)

        undone = api("POST", "merges/" + merged["merges"][0]["id"] + "/undo")
        restored = wait(lambda: indexed(talent_id))
        split = wait(lambda: indexed(undone["new_talent_id"]))
        assert len(restored["documents"]) == len(split["documents"]) == 1
        assert "PMP" not in restored["profile"]["certificates"] and "PMP" in split["profile"]["certificates"]
        for talent in (restored, split):
            document = talent["documents"][0]
            downloaded = client.get("documents/" + document["id"] + "/file")
            downloaded.raise_for_status()
            assert hashlib.sha256(downloaded.content).hexdigest() == document["sha256"]
        stale = client.put("talents/" + talent_id, json={"profile": original["profile"], "revision": original["revision"]})
        assert stale.status_code == 409
        result = {"status": "passed", "scope": "real API, PostgreSQL transactions, local model extraction and Milvus indexing",
                  "duration_seconds": round(time.monotonic() - started, 3), "synthetic_prefix": prefix,
                  "checks": ["200 files with hash reuse", "201-file rejection", "8 concurrent duplicate uploads",
                             "same-identity merge and history", "same-name identity conflict kept separate",
                             "merge undo with restored sources and certificates", "original file hashes", "stale edit rejected"],
                  "batch_id": batch["id"], "concurrent_batches": concurrent_batches,
                  "talent_ids": [talent_id, separate_id, undone["new_talent_id"]]}
        Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--output", default="data/runtime-reliability.json")
    args = parser.parse_args()
    password = os.environ.get("TALENT_ACCEPTANCE_PASSWORD")
    if not password:
        parser.error("TALENT_ACCEPTANCE_PASSWORD is required")
    run(args.base_url, password, args.output)
