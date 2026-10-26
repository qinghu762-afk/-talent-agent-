from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import urllib.request
paths=['api/controllers/console/setup.py','api/controllers/console/apikey.py','api/controllers/console/app/app_import.py','api/controllers/console/init_validate.py','api/controllers/console/datasets/datasets.py','api/controllers/console/workspace/tool_providers.py','api/controllers/console/wraps.py']
def get(p):
 target=Path(__file__).parent/'dify/upstream'/p;target.parent.mkdir(parents=True,exist_ok=True)
 try:
  with urllib.request.urlopen('https://raw.githubusercontent.com/langgenius/dify/1.17.1/'+p,timeout=30) as r: target.write_bytes(r.read())
  print(p,'OK')
 except Exception as e:print(p,str(e))
with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(get,paths))
