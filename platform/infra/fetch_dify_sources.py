from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import urllib.request
base='https://raw.githubusercontent.com/langgenius/dify/1.17.1/'
root=Path(__file__).parent/'dify'/'upstream'
paths=['docker/.env.example','docker/ssrf_proxy/squid.conf.template','docker/ssrf_proxy/squid-common.conf.template','docker/ssrf_proxy/docker-entrypoint.sh','docker/ssrf_proxy/squid-agent.conf.template','docker/ssrf_proxy/docker-agent-entrypoint.sh','docker/envs/core-services/shared.env.example','docker/envs/core-services/plugin-daemon.env.example','docker/envs/core-services/dify-agent.env.example','docker/envs/core-services/local-sandbox.env.example','api/controllers/console/auth/setup.py','api/controllers/console/auth/login.py','api/controllers/console/workspace/model_providers.py','api/controllers/console/workspace/models.py','api/controllers/console/app/app.py','api/controllers/console/app/workflow.py','api/controllers/console/app/api_key.py','api/controllers/console/workspace/plugin.py','api/controllers/console/app/imports.py']
def fetch(path):
    target=root/path
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(base+path, timeout=60) as response:
            target.write_bytes(response.read())
        print(path, 'OK')
    except Exception as exc: print(path, type(exc).__name__, str(exc))
with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(fetch,paths))
