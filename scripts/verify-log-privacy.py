"""Assert synthetic contact search values never appear in project request logs."""
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

import httpx


def main():
    tag = uuid4().hex
    email = "synthetic-log-" + tag + "@example.invalid"
    phone = "138" + str(int(tag[:12], 16) % 100000000).zfill(8)
    with httpx.Client(timeout=10, trust_env=False) as client:
        response = client.get("http://127.0.0.1:18080/api/v1/talents", params={"q": email + " " + phone})
        assert response.status_code == 401
    time.sleep(1)
    logs = subprocess.check_output(["docker", "compose", "-p", "talent-agent", "logs", "--since", "10s", "web", "api"],
                                   text=True, encoding="utf-8")
    assert email not in unquote(logs) and phone not in logs, "Full synthetic contact search appeared in request logs"
    output = {"status": "passed", "scope": "real unauthenticated contact search across web and API request logs",
              "checks": ["request remains authenticated", "no full email query value", "no full phone query value"]}
    Path("data/log-privacy.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print("Real request log contact-privacy check passed")


if __name__ == "__main__":
    main()
