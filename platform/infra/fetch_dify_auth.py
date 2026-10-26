import urllib.request
for p in ['api/libs/password.py','api/libs/csrf.py','api/libs/field_encryption.py','models/ollama/provider/ollama.yaml','models/ollama/models/llm/llm.py','models/ollama/models/text_embedding/text_embedding.py']:
 repo='dify-official-plugins/main/' if p.startswith('models/') else 'dify/1.17.1/'
 try:
  with urllib.request.urlopen('https://raw.githubusercontent.com/langgenius/'+repo+p,timeout=30) as r:s=r.read().decode()
  target=__import__('pathlib').Path(__file__).parent/'dify/upstream'/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(s,encoding='utf-8')
  print(p,'OK')
 except Exception as e:print(p,str(e))
