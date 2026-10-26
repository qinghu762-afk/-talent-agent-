import json,urllib.request
for u in ['https://api.github.com/repos/langgenius/dify-official-plugins/releases?per_page=100','https://raw.githubusercontent.com/langgenius/dify-official-plugins/main/models/ollama/manifest.yaml']:
 try:
  with urllib.request.urlopen(u,timeout=30) as r:data=r.read()
  if 'releases' in u:
   releases=json.loads(data)
   for x in releases:
    if 'ollama' in str(x).lower():print(json.dumps({'tag':x['tag_name'],'assets':[(a['name'],a['browser_download_url']) for a in x['assets']]}))
  else:print(data.decode()[:2000])
 except Exception as e:print(str(e))
