from pathlib import Path
import copy,json,yaml
root=Path(__file__).parents[1]
old=yaml.safe_load((root.parent/'compose.yaml').read_text('utf-8'))
official=yaml.safe_load((root/'infra/dify/upstream/docker-compose.yaml').read_text('utf-8'))
services={}
for name in ['etcd','minio','milvus','mineru']:
    services[name]=copy.deepcopy(old['services'][name])
    services[name]['networks']=['data']
    services[name].pop('build',None)
services['etcd']['environment']['ETCD_QUOTA_BACKEND_BYTES']='1073741824'
services['milvus']['environment'].update({'COMMON_STORAGETYPE':'remote','MQ_TYPE':'rocksmq'})
services['mineru']['volumes']=['mineru-models:/models:ro']
services['mineru']['tmpfs']=['/models/models/.locks:uid=10002,gid=10002,mode=0700']
services['mineru']['environment'].update({'OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2','MINERU_DEVICE_MODE':'cpu'})
services['mineru']['mem_limit']='4g'
services['postgres']={'image':'postgres:16.10-bookworm','restart':'unless-stopped','environment':{k:'${'+k+':?initialize configuration}' for k in ['POSTGRES_PASSWORD','ANALYTICS_PASSWORD','CHECKPOINT_PASSWORD','ANALYSIS_PASSWORD','DIFY_DB_PASSWORD','DIFY_PLUGIN_DB_PASSWORD']},'volumes':['postgres:/var/lib/postgresql/data','./infra/postgres-init.sh:/docker-entrypoint-initdb.d/20-platform.sh:ro'],'networks':['data','dify'],'healthcheck':{'test':['CMD-SHELL','pg_isready -U postgres -d postgres'],'interval':'10s','timeout':'5s','retries':30},'command':['postgres','-c','max_connections=160','-c','shared_buffers=128MB']}
services['mysql']={'image':'mysql:8.0','restart':'unless-stopped','environment':{'MYSQL_ROOT_PASSWORD':'${MYSQL_ROOT_PASSWORD:?initialize configuration}','MYSQL_ROOT_HOST':'%','MYSQL_DATABASE':'talent','MYSQL_USER':'talent','MYSQL_PASSWORD':'${MYSQL_PASSWORD:?initialize configuration}','MYSQL_ANALYSIS_PASSWORD':'${MYSQL_ANALYSIS_PASSWORD:?initialize configuration}'},'volumes':['mysql:/var/lib/mysql','./infra/mysql-init.sh:/docker-entrypoint-initdb.d/20-platform.sh:ro'],'networks':['data'],'command':['--innodb-buffer-pool-size=256M','--max-connections=100','--character-set-server=utf8mb4','--collation-server=utf8mb4_0900_ai_ci'],'healthcheck':{'test':['CMD-SHELL','MYSQL_PWD=$$MYSQL_ROOT_PASSWORD mysqladmin ping -h localhost --silent'],'interval':'10s','timeout':'5s','retries':30}}
for name,key,network in [('redis','REDIS_PASSWORD','data'),('dify-redis','DIFY_REDIS_PASSWORD','dify')]:
    services[name]={'image':'redis:7.4.5-alpine','restart':'unless-stopped','environment':{'REDIS_PASSWORD':'${'+key+':?initialize configuration}'},'entrypoint':['/bin/sh','-c','exec redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy noeviction --requirepass "$$REDIS_PASSWORD"'],'volumes':[name+':/data'],'networks':[network],'healthcheck':{'test':['CMD-SHELL','REDISCLI_AUTH=$$REDIS_PASSWORD redis-cli ping'],'interval':'10s','timeout':'5s','retries':12}}
env={
'MYSQL_URL':'mysql+asyncmy://talent:${MYSQL_PASSWORD}@mysql:3306/talent','POSTGRES_URL':'postgresql+asyncpg://talent_analytics:${ANALYTICS_PASSWORD}@postgres:5432/talent_analytics','CHECKPOINT_DATABASE_URL':'postgresql://talent_checkpoint:${CHECKPOINT_PASSWORD}@postgres:5432/talent_checkpoint','ANALYSIS_DATABASE_URL':'postgresql://talent_readonly:${ANALYSIS_PASSWORD}@postgres:5432/talent_analytics','MYSQL_ANALYSIS_URL':'mysql+pymysql://talent_readonly:${MYSQL_ANALYSIS_PASSWORD}@mysql:3306/talent','REDIS_URL':'redis://:${REDIS_PASSWORD}@redis:6379/0','MILVUS_URL':'http://milvus:19530','OLLAMA_URL':'http://model-gateway:11434','DIFY_API_URL':'http://dify-api:5001/v1','DIFY_APP_KEY':'${DIFY_APP_KEY:-}','DIFY_APP_ID':'${DIFY_APP_ID:-}','DIFY_WORKFLOW_HASH':'${DIFY_WORKFLOW_HASH:-}','CHAT_MODEL_DIGEST':'${CHAT_MODEL_DIGEST:-}','EMBEDDING_MODEL_DIGEST':'${EMBEDDING_MODEL_DIGEST:-}','PROMPT_VERSION':'${PROMPT_VERSION:-local-v2}','DIFY_DATASET_KEY':'${DIFY_DATASET_KEY:-}','DIFY_CONSOLE_URL':'http://127.0.0.1:18081','CHAT_MODEL':'${CHAT_MODEL:-qwen3:4b}','EMBEDDING_MODEL':'${EMBEDDING_MODEL:-bge-m3}','EMBEDDING_DIMENSION':'1024','PARSER_URL':'http://mineru:8001','DIFY_PUBLIC_URL':'http://127.0.0.1:18081','MINERU_URL':'http://mineru:8001','INTERNAL_SERVICE_KEY':'${INTERNAL_SERVICE_KEY:?initialize configuration}','JWT_SECRET':'${JWT_SECRET:?initialize configuration}','ADMIN_USERNAME':'${ADMIN_USERNAME:-admin}','ADMIN_PASSWORD':'${ADMIN_PASSWORD:?initialize configuration}','DATA_DIR':'/data','AI_SERVICE_URL':'http://ai:8001','ANALYTICS_SERVICE_URL':'http://analytics:8002','LANGCHAIN_TRACING_V2':'false','ANONYMIZED_TELEMETRY':'false'}
commands={'api':['uvicorn','talent_platform.api:app','--host','0.0.0.0','--port','8000','--no-access-log'],'ai':['uvicorn','talent_platform.ai_service:app','--host','0.0.0.0','--port','8001','--no-access-log'],'analytics':['uvicorn','talent_platform.analytics_service:app','--host','0.0.0.0','--port','8002','--no-access-log'],'worker':['python','-m','talent_platform.worker']}
for name,command in commands.items():
    services[name]={'image':'talent-platform-api:0.2.0','build':{'context':'.','dockerfile':'Dockerfile','args':{'HTTP_PROXY':'${BUILD_PROXY:-http://host.docker.internal:7897}','HTTPS_PROXY':'${BUILD_PROXY:-http://host.docker.internal:7897}'}},'restart':'unless-stopped','init':True,'environment':env.copy(),'volumes':['app-data:/data','./infra:/bootstrap:ro'],'networks':['data','application'],'command':command,'depends_on':{'mysql':{'condition':'service_healthy'},'postgres':{'condition':'service_healthy'},'redis':{'condition':'service_healthy'}}}
    if name!='worker':
        port={'api':8000,'ai':8001,'analytics':8002}[name]
        path='/api/v1/health' if name=='api' else '/health'
        services[name]['healthcheck']={'test':['CMD','python','-c',f"import urllib.request; urllib.request.urlopen('http://localhost:{port}{path}',timeout=5)"],'interval':'20s','timeout':'10s','start_period':'60s','retries':12}
services['worker']['depends_on'].update({'ai':{'condition':'service_healthy'},'analytics':{'condition':'service_healthy'}})
services['worker']['depends_on']['api']={'condition':'service_healthy'}
services['model-gateway']={'image':'talent-platform-gateway:0.2.0','build':{'context':'.','dockerfile':'infra/gateway.Dockerfile','args':{'HTTP_PROXY':'${BUILD_PROXY:-http://host.docker.internal:7897}','HTTPS_PROXY':'${BUILD_PROXY:-http://host.docker.internal:7897}'}},'restart':'unless-stopped','environment':{'OLLAMA_UPSTREAM':'http://host.docker.internal:11434','MODEL_MAX_PENDING':'64','MODEL_QUEUE_TIMEOUT':'900'},'extra_hosts':['host.docker.internal:host-gateway'],'networks':['data','dify','egress'],'healthcheck':{'test':['CMD','python','-c',"import urllib.request; urllib.request.urlopen('http://localhost:11434/health',timeout=5)"],'interval':'20s','timeout':'5s','retries':10}}
services['web']={'image':'talent-platform-web:0.2.0','build':{'context':'.','dockerfile':'infra/frontend.Dockerfile','args':{'HTTP_PROXY':'${BUILD_PROXY:-http://host.docker.internal:7897}','HTTPS_PROXY':'${BUILD_PROXY:-http://host.docker.internal:7897}'}},'restart':'unless-stopped','ports':['127.0.0.1:18080:8080'],'networks':['application'],'depends_on':{'api':{'condition':'service_healthy'}}}
# Retain every full Dify application feature; omit optional alternative database/vector/TLS providers only.
keep=['init_permissions','api','api_websocket','worker','worker_beat','web','sandbox','plugin_daemon','agent_backend','local_sandbox','agent_ssrf_proxy','ssrf_proxy','nginx']
mapping={name:'dify-'+name.replace('_','-') for name in keep}
def replace(value):
    if isinstance(value,str):
        for a,b in mapping.items(): value=value.replace('http://'+a+':','http://'+b+':')
        return value
    if isinstance(value,dict): return {k:replace(v) for k,v in value.items()}
    if isinstance(value,list): return [replace(v) for v in value]
    return value
shared={
'DEPLOY_ENV':'PRODUCTION','SECRET_KEY':'${DIFY_SECRET_KEY:?initialize configuration}','DB_TYPE':'postgresql','DB_HOST':'postgres','DB_PORT':'5432','DB_USERNAME':'dify','DB_PASSWORD':'${DIFY_DB_PASSWORD}','DB_DATABASE':'dify','REDIS_HOST':'dify-redis','REDIS_PORT':'6379','REDIS_PASSWORD':'${DIFY_REDIS_PASSWORD}','REDIS_DB':'0','CELERY_BROKER_URL':'redis://:${DIFY_REDIS_PASSWORD}@dify-redis:6379/1','STORAGE_TYPE':'opendal','OPENDAL_SCHEME':'fs','OPENDAL_FS_ROOT':'storage','VECTOR_STORE':'milvus','MILVUS_URI':'http://milvus:19530','MILVUS_DATABASE':'dify','MILVUS_USER':'','MILVUS_PASSWORD':'','MILVUS_ENABLE_HYBRID_SEARCH':'true','CODE_EXECUTION_ENDPOINT':'http://dify-sandbox:8194','CODE_EXECUTION_API_KEY':'${DIFY_SANDBOX_KEY}','SSRF_PROXY_HTTP_URL':'http://dify-ssrf-proxy:3128','SSRF_PROXY_HTTPS_URL':'http://dify-ssrf-proxy:3128','PLUGIN_DAEMON_URL':'http://dify-plugin-daemon:5002','PLUGIN_DAEMON_KEY':'${DIFY_PLUGIN_KEY}','INNER_API_KEY_FOR_PLUGIN':'${DIFY_INNER_KEY}','PLUGIN_DIFY_INNER_API_KEY':'${DIFY_INNER_KEY}','AGENT_BACKEND_BASE_URL':'http://dify-agent-backend:5050','AGENT_BACKEND_API_TOKEN':'${DIFY_AGENT_API_TOKEN}','DIFY_AGENT_API_TOKEN':'${DIFY_AGENT_API_TOKEN}','CONSOLE_WEB_URL':'http://127.0.0.1:18081','CONSOLE_API_URL':'http://127.0.0.1:18081','APP_WEB_URL':'http://127.0.0.1:18081','APP_API_URL':'http://127.0.0.1:18081','SERVICE_API_URL':'http://127.0.0.1:18081','FILES_URL':'http://127.0.0.1:18081','INTERNAL_FILES_URL':'http://dify-api:5001','SERVER_WORKER_AMOUNT':'1','SERVER_WORKER_CONNECTIONS':'20','SQLALCHEMY_POOL_SIZE':'5','SQLALCHEMY_MAX_OVERFLOW':'5','CELERY_WORKER_AMOUNT':'1','CELERY_WORKER_CLASS':'gevent','GUNICORN_TIMEOUT':'1800','TEXT_GENERATION_TIMEOUT_MS':'1800000','APP_MAX_EXECUTION_TIME':'1800','WORKFLOW_MAX_EXECUTION_TIME':'1800','ENABLE_COLLABORATION_MODE':'true','NEXT_TELEMETRY_DISABLED':'1','ENABLE_EMAIL_PASSWORD_LOGIN':'true'}
for name in keep:
    service=replace(copy.deepcopy(official['services'][name]))
    for key in ['env_file','profiles','ports','networks','depends_on','volumes']: service.pop(key,None)
    service['restart']='unless-stopped' if name!='init_permissions' else 'no'
    service['networks']=['dify']
    e=service.setdefault('environment',{})
    if name in ['api','api_websocket','worker','worker_beat']: service['environment']={**e,**shared,'MODE':{'api':'api','api_websocket':'api','worker':'worker','worker_beat':'beat'}[name]}
    if name in ['api','api_websocket','worker']:
        service['volumes']=['dify-storage:/app/api/storage']
    if name in ['api','api_websocket','worker','worker_beat','plugin_daemon']:
        service['depends_on']={'postgres':{'condition':'service_healthy'},'dify-redis':{'condition':'service_healthy'}}
        if name!='plugin_daemon': service['depends_on']['dify-init-permissions']={'condition':'service_completed_successfully'}
    if name=='init_permissions':
        service['image']='busybox@sha256:dc2d74b28e4cf8984fa52af1f39bc7c3d9c73760b41a74d629f5d11b1ab28616'
        service['volumes']=['dify-storage:/app/api/storage']
    if name=='web':
        service['environment'].update({'CONSOLE_API_URL':'http://127.0.0.1:18081','APP_API_URL':'http://127.0.0.1:18081','SERVER_CONSOLE_API_URL':'http://dify-api:5001','NEXT_PUBLIC_SOCKET_URL':'ws://127.0.0.1:18081','NEXT_TELEMETRY_DISABLED':'1'})
    if name=='sandbox':
        e.update({'API_KEY':'${DIFY_SANDBOX_KEY}','HTTP_PROXY':'http://dify-ssrf-proxy:3128','HTTPS_PROXY':'http://dify-ssrf-proxy:3128'})
        service['volumes']=['dify-sandbox-deps:/dependencies','dify-sandbox-conf:/conf']; service['networks']=['dify-sandbox']
    if name=='plugin_daemon':
        e.update({'UV_NO_INDEX':'true','UV_FIND_LINKS':'/offline-wheels'})
        e.update({'HTTP_PROXY':'http://host.docker.internal:7897','HTTPS_PROXY':'http://host.docker.internal:7897','NO_PROXY':'localhost,127.0.0.1,dify-api,dify-plugin-daemon,dify-redis,postgres,milvus,model-gateway,platform-api','UV_HTTP_TIMEOUT':'60','UV_HTTP_CONCURRENT_DOWNLOADS':'8'})
        e.update({**shared,'DB_USERNAME':'dify_plugin','DB_PASSWORD':'${DIFY_PLUGIN_DB_PASSWORD}','DB_DATABASE':'dify_plugin','SERVER_KEY':'${DIFY_PLUGIN_KEY}','DIFY_INNER_API_URL':'http://dify-api:5001','DIFY_INNER_API_KEY':'${DIFY_INNER_KEY}','PYTHON_ENV_INIT_TIMEOUT':'600','PIP_MIRROR_URL':'https://pypi.org/simple'})
        service['volumes']=['dify-plugins:/app/storage','./infra/dify/wheels:/offline-wheels:ro']; service['networks']=['dify','egress']
    if name=='agent_backend':
        e.update({'DIFY_AGENT_REDIS_URL':'redis://:${DIFY_REDIS_PASSWORD}@dify-redis:6379/2','DIFY_AGENT_PLUGIN_DAEMON_URL':'http://dify-plugin-daemon:5002','DIFY_AGENT_PLUGIN_DAEMON_API_KEY':'${DIFY_PLUGIN_KEY}','DIFY_AGENT_INNER_API_URL':'http://dify-api:5001','DIFY_AGENT_INNER_API_KEY':'${DIFY_INNER_KEY}','DIFY_AGENT_SERVER_SECRET_KEY':'${DIFY_AGENT_SECRET}','DIFY_AGENT_API_TOKEN':'${DIFY_AGENT_API_TOKEN}','DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN':'${DIFY_SHELL_TOKEN}','DIFY_AGENT_LOCAL_SANDBOX_ENDPOINT':'http://dify-local-sandbox:5004','DIFY_AGENT_STUB_API_BASE_URL':'http://dify-agent-backend:5050/agent-stub','DIFY_AGENT_SANDBOX_FILES_BASE_URL':'http://dify-api:5001'})
        service['networks']=['dify','dify-agent']; service['depends_on']={'dify-redis':{'condition':'service_healthy'},'dify-plugin-daemon':{'condition':'service_started'}}
    if name=='local_sandbox':
        service['environment']={'SHELLCTL_AUTH_TOKEN':'${DIFY_SHELL_TOKEN}','HTTP_PROXY':'http://dify-agent-ssrf-proxy:3128','HTTPS_PROXY':'http://dify-agent-ssrf-proxy:3128','NO_PROXY':'localhost,127.0.0.1'}
        service['volumes']=['dify-agent-home:/home/dify','dify-agent-workspace:/workspace'];service['networks']=['dify-agent','dify-agent-proxy']
    if name in ['ssrf_proxy','agent_ssrf_proxy']:
        agent=name=='agent_ssrf_proxy'
        service['image']='ubuntu/squid@sha256:6a097f68bae708cedbabd6188d68c7e2e7a38cedd05a176e1cc0ba29e3bbe029'
        prefix='./infra/dify/upstream/docker/ssrf_proxy/'
        service['volumes']=[prefix+('squid-agent.conf.template' if agent else 'squid.conf.template')+':/etc/squid/squid.conf.template:ro',prefix+'squid-common.conf.template:/etc/squid/dify_common.conf.template:ro',prefix+('docker-agent-entrypoint.sh' if agent else 'docker-entrypoint.sh')+':/docker-entrypoint-mount.sh:ro']
        service['networks']=['dify','dify-agent-proxy','egress'] if agent else ['dify','dify-sandbox','egress']
        e['SSRF_PROXY_ALLOW_PRIVATE_DOMAINS']='dify-api,dify-agent-backend' if agent else 'model-gateway,platform-api'
        if not agent: service['networks'].append('data')
        # Agent proxy templates use the official DNS aliases.
        if agent:
            services['dify-api']['networks']={'dify':{'aliases':['api']}}
            services['dify-agent-backend']['networks']={'dify':{'aliases':['agent_backend']},'dify-agent':{}}
    if name=='nginx':
        service['networks']=['dify','application']
        service['image']='nginx:1.28.0-alpine';service.pop('entrypoint',None);service.pop('environment',None)
        service['volumes']=['./infra/dify/nginx.conf:/etc/nginx/conf.d/default.conf:ro'];service['ports']=['127.0.0.1:18081:80']; service['depends_on']={'dify-api':{'condition':'service_started'},'dify-web':{'condition':'service_started'},'dify-api-websocket':{'condition':'service_started'}}
    services[mapping[name]]=service
services['dify-api']['networks']={'dify':{'aliases':['api']},'data':{}}
services['dify-worker']['networks']=['dify','data']
services['dify-api-websocket']['networks']=['dify','data']
services['api']['networks']={'data':{'aliases':['platform-api']},'application':{}}
services['milvus-init']={'image':'talent-platform-api:0.2.0','restart':'no','command':['python','/bootstrap/init_milvus.py'],'volumes':['./infra/init_milvus.py:/bootstrap/init_milvus.py:ro'],'networks':['data'],'depends_on':{'milvus':{'condition':'service_healthy'}}}
for service_name in ['dify-api','dify-worker','dify-api-websocket']:services[service_name]['depends_on']['milvus-init']={'condition':'service_completed_successfully'}
volumes={name:{} for name in ['postgres','mysql','redis','etcd','minio','milvus','app-data','dify-redis','dify-storage','dify-sandbox-deps','dify-sandbox-conf','dify-plugins','dify-agent-home','dify-agent-workspace']}
volumes['mineru-models']={'external':True,'name':'talent-agent_mineru-models'}
compose={'name':'talent-platform','services':services,'networks':{n:({'internal':True} if n!='egress' and n!='application' else {}) for n in ['data','application','dify','dify-sandbox','dify-agent','dify-agent-proxy','egress']},'volumes':volumes}
image_lock=json.loads((root/'infra/images.lock.json').read_text('utf-8'))['images']
for service in services.values():service['image']=image_lock.get(service['image'],service['image'])
(root/'compose.yaml').write_text('# Derived from official langgenius/dify tag 1.17.1; see infra/dify/upstream.\n'+yaml.safe_dump(compose,sort_keys=False,allow_unicode=True),encoding='utf-8')
print('Wrote isolated compose:',len(services),'services')
