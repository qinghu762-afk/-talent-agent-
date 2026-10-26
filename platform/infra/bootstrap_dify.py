"""Bootstrap exclusively the independent Dify on 127.0.0.1:18081.

Never prints credentials. All state and keys are persisted in the new .env.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import zipfile

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROVIDER = 'langgenius/ollama/ollama'


def validate_plugin(package):
    """Verify pinned bytes and official identity before uploading code."""
    metadata=json.loads((ROOT/'infra/dify/ollama-package.json').read_text('utf-8'))
    if hashlib.sha256(package.read_bytes()).hexdigest()!=metadata['sha256']:
        raise ValueError('Ollama package checksum mismatch')
    with zipfile.ZipFile(package) as archive:
        manifest=yaml.safe_load(archive.read('manifest.yaml'))
    if any(str(manifest.get(key))!=metadata[key] for key in ['author','name','version']):
        raise ValueError('Ollama package identity mismatch')
    return metadata['identifier']


def validate_target(url):
    if url != 'http://127.0.0.1:18081':
        raise ValueError('Bootstrap is restricted to the new independent Dify on 127.0.0.1:18081')
    return url


def workflow_dsl(model):
    def node(identifier, kind, title, x, extra):
        return {'id': identifier, 'type':'custom', 'position':{'x':x,'y':180}, 'data':{'type':kind,'title':title,'desc':'',**extra}, 'width':244,'height':96}
    nodes=[
        node('start','start','业务提示输入',50,{'variables':[{'variable':'prompt','label':'业务提示','type':'paragraph','required':True,'max_length':150000}]}),
        node('llm','llm','本地证据分析',380,{'context':{'enabled':False,'variable_selector':[]},'model':{'provider':PROVIDER,'name':model,'mode':'chat','completion_params':{'temperature':0,'think':False,'format':'json','num_ctx':8192,'num_predict':4000,'json_schema':(ROOT/'infra/dify/output-schema.json').read_text('utf-8')}},'prompt_template':[{'id':'system','role':'system','text':'你是企业人才平台的本地分析模型。严格遵循用户给出的结构和授权范围。只根据提供的材料作答，不虚构经历、分数、引用或数据。材料不足时明确标记未知。若要求JSON则仅输出合法JSON。'},{'id':'user','role':'user','text':'{{#start.prompt#}}'}],'vision':{'enabled':False}}),
        node('end','end','分析文本输出',710,{'outputs':[{'variable':'text','value_selector':['llm','text'],'value_type':'string'}]})]
    edges=[{'id':a+'-'+b,'type':'custom','source':a,'target':b,'sourceHandle':'source','targetHandle':'target','data':{'sourceType':at,'targetType':bt,'isInIteration':False}} for a,b,at,bt in [('start','llm','start','llm'),('llm','end','llm','end')]]
    return {'version':'0.3.0','kind':'app','app':{'name':'人才平台通用工作流','mode':'workflow','description':'本地证据分析：人才、岗位、匹配、知识、培训与报告。','icon':'🤝','icon_background':'#E8F1EC','use_icon_as_answer_icon':False},'dependencies':[],'workflow':{'graph':{'nodes':nodes,'edges':edges,'viewport':{'x':0,'y':0,'zoom':0.8}},'features':{'file_upload':{'enabled':False},'opening_statement':'','retriever_resource':{'enabled':True},'sensitive_word_avoidance':{'enabled':False},'speech_to_text':{'enabled':False},'suggested_questions':[],'suggested_questions_after_answer':{'enabled':False},'text_to_speech':{'enabled':False}},'environment_variables':[],'conversation_variables':[]}}


def skills_schema():
    return {'openapi': '3.0.3', 'info': {'title': '人才平台授权技能', 'version': '1.1.0',
            'description': '执行已启用技能并回查真实异步结果；组织与权限由平台复核。'},
            'servers': [{'url': 'http://platform-api:8000'}], 'paths': {
                '/api/v1/integrations/dify/skills/execute': {'post': {
                    'operationId': 'executeTalentSkill', 'summary': '执行授权人才技能，返回运行ID',
                    'requestBody': {'required': True, 'content': {'application/json': {'schema': {
                        'type': 'object', 'required': ['skill_id', 'parameters', 'org_id'], 'properties': {
                            'skill_id': {'type': 'string'}, 'org_id': {'type': 'string'},
                            'parameters': {'type': 'object', 'additionalProperties': True}}}}}},
                    'responses': {'202': {'description': '已创建异步任务，请使用运行ID回查'}}}},
                '/api/v1/integrations/dify/runs/{run_id}': {'get': {
                    'operationId': 'getTalentSkillResult', 'summary': '回查授权技能及业务子任务结果',
                    'parameters': [{'name': 'run_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'string'}}],
                    'responses': {'200': {'description': '业务子任务状态、版本与结果；queued/running时继续等待'}}}}
            }}


class Bootstrap:
    def __init__(self, url, env_path):
        self.url=validate_target(url)
        self.env_path=Path(env_path)
        if self.env_path.resolve() != (ROOT/'.env').resolve():
            raise ValueError('Only platform/.env can be used for new bootstrap state')
        self.values={line.split('=',1)[0]:line.split('=',1)[1].strip() for line in self.env_path.read_text('utf-8-sig').splitlines() if '=' in line and not line.lstrip().startswith('#')}
        self.client=httpx.Client(base_url=self.url+'/console/api',timeout=120,trust_env=False,headers={'Origin':self.url,'Referer':self.url+'/'})

    def save(self, **values):
        content=self.env_path.read_text('utf-8-sig')
        for name,value in values.items():
            if '\n' in value or '\r' in value: raise ValueError('Invalid env value')
            pattern=r'(?m)^'+re.escape(name)+r'=[^\r\n]*'
            if re.search(pattern,content): content=re.sub(pattern,lambda _:name+'='+value,content)
            else: content+='\n'+name+'='+value+'\n'
            self.values[name]=value
        if os.name=='nt':
            # Preserve the existing private Windows DACL; replacing with a new
            # temporary file could inherit broader directory permissions.
            with self.env_path.open('w',encoding='utf-8') as output:
                output.write(content);output.flush();os.fsync(output.fileno())
        else:
            temporary=self.env_path.with_suffix('.env.next')
            temporary.write_text(content,encoding='utf-8')
            os.chmod(temporary,0o600)
            os.replace(temporary,self.env_path)

    def call(self, method, path, **kwargs):
        csrf=next((cookie.value for cookie in self.client.cookies.jar if 'csrf' in cookie.name.lower()),None)
        if csrf:self.client.headers['X-CSRF-Token']=csrf
        response=self.client.request(method,path,**kwargs)
        if response.status_code >=400:
            raise RuntimeError(f'New Dify bootstrap {method} {path} returned HTTP {response.status_code}; response omitted to protect secrets')
        return response.json() if response.content else {}

    def wait(self):
        for _ in range(120):
            try:
                response=self.client.get('/setup')
                if response.status_code==200:return response.json()
            except httpx.HTTPError:pass
            time.sleep(3)
        raise RuntimeError('Independent Dify did not become ready within six minutes')

    def setup(self):
        status=self.wait()
        if status.get('step')=='not_started':
            self.call('POST','/setup',json={'email':self.values['DIFY_ADMIN_EMAIL'],'name':'人才平台管理员','password':self.values['DIFY_ADMIN_PASSWORD'],'language':'zh-Hans'})
        self.call('POST','/login',json={'email':self.values['DIFY_ADMIN_EMAIL'],'password':base64.b64encode(self.values['DIFY_ADMIN_PASSWORD'].encode()).decode(),'remember_me':False})
        print('New dedicated Dify administrator authenticated.')

    def plugin(self):
        def installed():
            result=self.call('GET','/workspaces/current/plugin/list',params={'page':1,'page_size':256})
            items=result.get('plugins',result.get('data',[]))
            return any('langgenius/ollama' in str(item.get('plugin_unique_identifier',item.get('plugin_id',''))) for item in items)
        if not installed():
            package=ROOT/'infra/dify/ollama.difypkg'
            identifier=self.values.get('DIFY_OLLAMA_PLUGIN_ID','')
            if package.exists():
                expected_identifier=validate_plugin(package)
                with package.open('rb') as source:
                    decoded=self.call('POST','/workspaces/current/plugin/upload/pkg',files={'pkg':('ollama.difypkg',source,'application/octet-stream')})
                identifier=decoded.get('unique_identifier') or decoded.get('plugin_unique_identifier')
                if not identifier and isinstance(decoded.get('data'),dict):identifier=decoded['data'].get('unique_identifier')
                if not identifier:raise RuntimeError('Ollama package upload did not return its identifier')
                if identifier!=expected_identifier:raise RuntimeError('Uploaded package identifier differs from the official pinned package')
                self.call('POST','/workspaces/current/plugin/install/pkg',json={'plugin_unique_identifiers':[identifier]})
            elif identifier:
                self.call('POST','/workspaces/current/plugin/install/marketplace',json={'plugin_unique_identifiers':[identifier]})
            else:
                raise RuntimeError('Place the official signed Ollama package in platform/infra/dify/ollama.difypkg or set DIFY_OLLAMA_PLUGIN_ID to its pinned marketplace identifier')
            self.save(DIFY_OLLAMA_PLUGIN_ID=identifier)
            for _ in range(180):
                if installed():break
                time.sleep(5)
            else:raise RuntimeError('Ollama plugin installation did not complete in fifteen minutes')
        print('Official Ollama provider installed in the new workspace.')

    def models(self):
        for kind,key in [('llm','CHAT_MODEL'),('text-embedding','EMBEDDING_MODEL')]:
            model=self.values[key]
            base=f'/workspaces/current/model-providers/{PROVIDER}/models/credentials'
            result=self.call('GET',base,params={'model':model,'model_type':kind})
            if not result.get('current_credential_id'):
                credentials={'base_url':'http://model-gateway:11434','context_size':'16384'}
                if kind=='llm':credentials.update({'mode':'chat','max_tokens':'8192','vision_support':'false','function_call_support':'false'})
                self.call('POST',base,json={'model':model,'model_type':kind,'name':'platform-serial-gateway','credentials':credentials})
            elif result.get('credentials',{}).get('base_url')!='http://model-gateway:11434':
                raise RuntimeError('Existing new-workspace model points outside the serial gateway; inspect dedicated configuration')
        self.call('POST','/workspaces/current/default-model',json={'model_settings':[{'model_type':kind,'provider':PROVIDER,'model':self.values[key]} for kind,key in [('llm','CHAT_MODEL'),('text-embedding','EMBEDDING_MODEL')]]})
        print('Chat and embeddings share the single serial model gateway.')

    def application(self):
        app_id=self.values.get('DIFY_APP_ID')
        if not app_id:
            existing=self.call('GET','/apps',params={'page':1,'limit':100}).get('data',[])
            match=next((item for item in existing if item.get('name')=='人才平台通用工作流'),None)
            if match:app_id=match['id']
            else:
                result=self.call('POST','/apps/imports',json={'mode':'yaml-content','yaml_content':yaml.safe_dump(workflow_dsl(self.values['CHAT_MODEL']),allow_unicode=True,sort_keys=False)})
                if result.get('status')=='pending':result=self.call('POST',f"/apps/imports/{result['id']}/confirm",json={})
                app_id=result.get('app_id')
                if not app_id:raise RuntimeError('Workflow import failed to produce an application id')
            self.save(DIFY_APP_ID=app_id)
        workflow=workflow_dsl(self.values['CHAT_MODEL'])['workflow']
        draft=self.call('GET',f'/apps/{app_id}/workflows/draft')
        self.call('POST',f'/apps/{app_id}/workflows/draft',json={'graph':workflow['graph'],'features':workflow['features'],'conversation_variables':[], 'hash':draft.get('hash')})
        self.call('POST',f'/apps/{app_id}/workflows/publish',json={})
        self.save(DIFY_WORKFLOW_HASH=hashlib.sha256(json.dumps(workflow,sort_keys=True,ensure_ascii=False).encode()).hexdigest())
        if not self.values.get('DIFY_APP_KEY'):
            # Dify 1.17.1 lists masked tokens. Only creation reveals a usable key.
            key=self.call('POST',f'/apps/{app_id}/api-keys',json={})
            self.save(DIFY_APP_KEY=key['token'])
        if not self.values.get('DIFY_DATASET_KEY'):
            result=self.call('POST','/datasets/api-keys',json={'dataset_ids':[]})
            self.save(DIFY_DATASET_KEY=result['token'])
        (ROOT/'infra/dify/talent-workflow.yaml').write_text(yaml.safe_dump(workflow_dsl(self.values['CHAT_MODEL']),allow_unicode=True,sort_keys=False),encoding='utf-8')
        print('Generic workflow published; application and dataset keys saved privately.')

    def tools(self):
        schema = skills_schema()
        encoded = json.dumps(schema, ensure_ascii=False, sort_keys=True)
        (ROOT/'infra/dify/skills-openapi.json').write_text(encoded, encoding='utf-8')
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        if self.values.get('DIFY_TOOLS_SCHEMA_HASH') != digest:
            payload = {'provider': '人才平台授权技能', 'schema_type': 'openapi', 'schema': encoded,
                       'icon': {'content': '🛠️', 'background': '#E8F1EC'},
                       'credentials': {'auth_type': 'api_key_header', 'api_key_header': 'X-Service-Key',
                                       'api_key_value': self.values['INTERNAL_SERVICE_KEY'], 'api_key_header_prefix': 'custom'},
                       'privacy_policy': '', 'labels': []}
            operation = 'update' if self.values.get('DIFY_TOOLS_IMPORTED') == 'true' else 'add'
            if operation == 'update':
                payload['original_provider'] = payload['provider']
            self.call('POST', '/workspaces/current/tool-provider/api/' + operation, json=payload)
            self.save(DIFY_TOOLS_IMPORTED='true', DIFY_TOOLS_SCHEMA_HASH=digest)
        print('Platform Skills execute and result tools imported into independent Dify.')



def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:18081')
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    validate_target(args.url)
    if args.dry_run:
        print('PLAN: only new local Dify; new administrator, signed Ollama plugin, serial-gateway models, prompt workflow, Skills tool and keys in platform/.env')
        return
    instance=Bootstrap(args.url,args.env_file)
    try:
        instance.setup();instance.plugin();instance.models();instance.application();instance.tools()
    finally:instance.client.close()


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(str(exc),file=sys.stderr)
        sys.exit(1)
