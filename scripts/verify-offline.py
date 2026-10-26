"""Disconnect only this project's container egress; restore all routes on exit."""
import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw, ImageFont


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8", check=check)


def main(base_url, output):
    password = os.environ.get("TALENT_ACCEPTANCE_PASSWORD")
    if not password:
        raise ValueError("TALENT_ACCEPTANCE_PASSWORD is required")
    changed = []
    report = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "talent-agent containers only; host and other projects remain online", "network_probes": {}}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    def net(container, *args, check=True):
        return docker("run", "--rm", "--pull", "never", "--network", "container:" + container,
                      "--cap-add", "NET_ADMIN", "--entrypoint", "ip", "nginx:1.28.0-alpine", *args, check=check)

    try:
        for service in ("web", "ollama"):
            container = docker("compose", "-p", "talent-agent", "ps", "-q", service).stdout.strip()
            if not container:
                raise RuntimeError("Missing talent service: " + service)
            owner = docker("inspect", container, "--format", '{{index .Config.Labels "com.docker.compose.project"}}').stdout.strip()
            if owner != "talent-agent":
                raise RuntimeError("Refusing a container outside talent-agent")
            routes = docker("exec", container, "ip", "-4", "route").stdout.splitlines()
            if docker("exec", container, "ip", "-6", "route", "show", "default").stdout.strip():
                raise RuntimeError("Unexpected IPv6 default route; test needs explicit IPv6 handling")
            default = next((r for r in routes if r.startswith("default ")), None)
            if not default:
                raise RuntimeError("Missing expected project gateway route")
            original = shlex.split(default)
            host_route = None
            if service == "ollama":
                hosts = docker("exec", container, "cat", "/etc/hosts").stdout
                match = re.search(r"^(\d+\.\d+\.\d+\.\d+)\s+host\.docker\.internal", hosts, re.M)
                if not match:
                    raise RuntimeError("Cannot identify the existing local Ollama host route")
                host_route = [match[1] + "/32", *original[1:]]
                net(container, "-4", "route", "add", *host_route)
            changed.append((container, original, host_route))
            net(container, "-4", "route", "del", "default")
            blocked = docker("exec", container, "ip", "-4", "route", "get", "1.1.1.1", check=False)
            if blocked.returncode == 0:
                raise AssertionError("Public route remained available for " + service)
            report["network_probes"][service] = {"public_ip": "1.1.1.1", "blocked": True,
                                                  "reason": blocked.stderr.strip(), "local_host_route": host_route}
        for service in ("api", "mineru"):
            container = docker("compose", "-p", "talent-agent", "ps", "-q", service).stdout.strip()
            probe = docker("exec", container, "python", "-c",
                           "import socket; socket.create_connection(('1.1.1.1',443),timeout=2)", check=False)
            if probe.returncode == 0:
                raise AssertionError("Public TCP connection succeeded for " + service)
            report["network_probes"][service] = {"public_ip": "1.1.1.1:443", "blocked": True,
                                                  "reason": probe.stderr.strip().splitlines()[-1]}
        with httpx.Client(base_url=base_url.rstrip("/") + "/api/v1/", timeout=45, trust_env=False) as client:
            def api(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()

            def wait(fetch):
                deadline = time.monotonic() + 900
                while time.monotonic() < deadline:
                    value = fetch()
                    if value:
                        return value
                    time.sleep(2)
                raise TimeoutError("Offline workflow timed out")

            api("POST", "auth/login", json={"username": "admin", "password": password})
            system = api("GET", "system")
            assert all(v["ok"] for v in system["services"].values())
            tag = uuid4().hex[:8]
            text = ("合成测试简历，非真实个人\n姓名：离线合成人才甲\n"
                    f"邮箱：offline{tag}@example.invalid\n地点：北京\n技能：Python、PostgreSQL\n"
                    "公司：合成技术公司\n职位：Python工程师\n开始日期：2020-01\n结束日期：2024-01\n学历：本科")
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 34)
            image = Image.new("RGB", (1240, 1754), "white")
            ImageDraw.Draw(image).multiline_text((50, 50), text, font=font, fill="black", spacing=20)
            scan = output.parent / ("offline-synthetic-" + tag + ".png")
            image.save(scan)
            batch = api("POST", "batches", files={"files": (scan.name, scan.read_bytes(), "image/png")})

            def parsed():
                item = api("GET", "batches/" + batch["id"])["items"][0]
                if item["status"] == "failed":
                    raise AssertionError("Fresh offline scan failed")
                if not item.get("talent_id"):
                    return None
                talent = api("GET", "talents/" + item["talent_id"])
                return talent if talent["revision"] == talent["indexed_revision"] and talent["index_model"] else None

            talent = wait(parsed)
            assert talent["profile"]["name"] == "离线合成人才甲"
            assert talent["profile"]["experience_months"] == 48
            assert {"Python", "PostgreSQL"} <= set(talent["profile"]["skills"])
            original = client.get("documents/" + talent["documents"][0]["id"] + "/file")
            original.raise_for_status()
            assert hashlib.sha256(original.content).digest() == hashlib.sha256(scan.read_bytes()).digest()
            job = api("POST", "jobs", json={"title": "合成离线 Python 岗位 " + tag,
                "description": "必须掌握Python；PostgreSQL优先。至少三年工作经验。本科学历。工作地点：北京。"})

            def parsed_job():
                value = next(j for j in api("GET", "jobs") if j["id"] == job["id"])
                if value["status"] == "failed":
                    raise AssertionError("Fresh offline job failed")
                return value if value["status"] == "completed" else None

            job = wait(parsed_job)
            assert job["requirements"]["min_experience_months"] == 36
            assert "Python" in job["requirements"]["required_skills"]
            match = api("POST", "jobs/" + job["id"] + "/matches")

            def matched():
                value = api("GET", "matches/" + match["id"])
                if value["status"] == "failed":
                    raise AssertionError("Offline match failed")
                return value if value["status"] == "completed" else None

            match = wait(matched)
            assert any(r["talent_id"] == talent["id"] for r in match["results"])
            assert all(c["status"] == "pass" for r in match["results"] for c in r["score"]["conditions"])
            report.update(status="passed", offline_network_verified=True, batch_id=batch["id"],
                          talent_id=talent["id"], job_id=job["id"], match_id=match["id"],
                          source_sha256=hashlib.sha256(scan.read_bytes()).hexdigest(), system=system)
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        restored = []
        for container, original, host_route in reversed(changed):
            result = net(container, "-4", "route", "add", *original, check=False)
            if host_route:
                net(container, "-4", "route", "del", *host_route, check=False)
            restored.append({"container": container, "restored": result.returncode == 0})
        report["routes_restored"] = restored
        if not all(r["restored"] for r in restored):
            report["status"] = "failed"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: report.get(k) for k in ("status", "scope", "offline_network_verified", "routes_restored")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--output", default="data/acceptance-offline-project.json")
    args = parser.parse_args()
    main(args.base_url, args.output)
