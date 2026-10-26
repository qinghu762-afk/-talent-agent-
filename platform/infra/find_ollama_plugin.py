import urllib.request,json
for u in ['https://marketplace.dify.ai/api/v1/plugins/langgenius/ollama/latest','https://marketplace.dify.ai/api/v1/plugins/langgenius/ollama']:
 try:
  with urllib.request.urlopen(u,timeout=30) as r: data=r.read()
  print(u,data[:3000].decode())
 except Exception as e:print(u,str(e))
