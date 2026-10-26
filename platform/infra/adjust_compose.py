from pathlib import Path
p=Path(__file__).parent/'generate_compose.py'
s=p.read_text('utf-8-sig')
s=s.replace("'MINERU_URL':'http://mineru:8001'", "'PARSER_URL':'http://mineru:8001','DIFY_PUBLIC_URL':'http://127.0.0.1:18081','MINERU_URL':'http://mineru:8001'")
s=s.replace("'volumes':['app-data:/data']", "'volumes':['app-data:/data','./infra:/bootstrap:ro']")
s=s.replace("e['SSRF_PROXY_ALLOW_PRIVATE_DOMAINS']='dify-api,dify-agent-backend' if agent else 'model-gateway,api'", "e['SSRF_PROXY_ALLOW_PRIVATE_DOMAINS']='dify-api,dify-agent-backend' if agent else 'model-gateway,platform-api'\n        if not agent: service['networks'].append('data')")
s=s.replace("services['dify-api']['networks']={'dify'", "services['api']['networks']={'data':{'aliases':['platform-api']},'application':{}}\nservices['milvus-init']={'image':'talent-platform-api:0.2.0','restart':'no','command':['python','/bootstrap/init_milvus.py'],'volumes':['./infra/init_milvus.py:/bootstrap/init_milvus.py:ro'],'networks':['data'],'depends_on':{'milvus':{'condition':'service_healthy'}}}\nfor service_name in ['dify-api','dify-worker','dify-api-websocket']:services[service_name]['depends_on']['milvus-init']={'condition':'service_completed_successfully'}\nservices['dify-api']['networks']={'dify'",1) if False else s
# Append explicit finalization before volume definitions.
needle="volumes={name:{}"
insert="""services['api']['networks']={'data':{'aliases':['platform-api']},'application':{}}
services['milvus-init']={'image':'talent-platform-api:0.2.0','restart':'no','command':['python','/bootstrap/init_milvus.py'],'volumes':['./infra/init_milvus.py:/bootstrap/init_milvus.py:ro'],'networks':['data'],'depends_on':{'milvus':{'condition':'service_healthy'}}}
for service_name in ['dify-api','dify-worker','dify-api-websocket']:services[service_name]['depends_on']['milvus-init']={'condition':'service_completed_successfully'}
"""
s=s.replace(needle,insert+needle)
p.write_text(s,encoding='utf-8')
