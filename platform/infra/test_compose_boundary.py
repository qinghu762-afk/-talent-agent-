from pathlib import Path
import re,unittest,yaml
ROOT=Path(__file__).parents[1]
class ComposeBoundary(unittest.TestCase):
 def setUp(self):self.config=yaml.safe_load((ROOT/'compose.yaml').read_text('utf-8-sig'))
 def test_only_new_loopback_ingress_and_readonly_legacy_weights(self):
  self.assertEqual(self.config['name'],'talent-platform')
  ports=[port for svc in self.config['services'].values() for port in svc.get('ports',[])]
  self.assertEqual(sorted(ports),['127.0.0.1:18080:8080','127.0.0.1:18081:80'])
  external=[(name,vol) for name,vol in self.config['volumes'].items() if vol.get('external')]
  self.assertEqual(external,[('mineru-models',{'external':True,'name':'talent-agent_mineru-models'})])
  self.assertEqual(self.config['services']['mineru']['volumes'],['mineru-models:/models:ro'])
  self.assertEqual(self.config['services']['mineru'].get('tmpfs'), ['/models/models/.locks:uid=10002,gid=10002,mode=0700'])
  self.assertNotIn('build',self.config['services']['mineru'])
 def test_all_dify_features_and_new_data_dependencies_are_present(self):
  required={'dify-api','dify-web','dify-worker','dify-worker-beat','dify-api-websocket','dify-agent-backend','dify-local-sandbox','dify-agent-ssrf-proxy','dify-ssrf-proxy','dify-sandbox','dify-plugin-daemon','mysql','postgres','milvus','redis','dify-redis','model-gateway'}
  self.assertTrue(required <= self.config['services'].keys())
  for name in ['api','ai','analytics','worker']:
   self.assertEqual(self.config['services'][name]['environment']['OLLAMA_URL'],'http://model-gateway:11434')
  self.assertEqual(self.config['services']['dify-plugin-daemon']['environment']['DB_USERNAME'],'dify_plugin')
  self.assertEqual(self.config['services']['dify-api']['environment']['DB_USERNAME'],'dify')
 def test_all_required_interpolation_variables_have_env_template_entries(self):
  template=(ROOT/'.env.example').read_text('utf-8-sig')
  names={line.split('=',1)[0] for line in template.splitlines() if '=' in line}
  required=set(re.findall(r'\$\{([A-Z_]+):\?',(ROOT/'compose.yaml').read_text('utf-8-sig')))
  self.assertTrue(required<=names,required-names)
 def test_public_and_reused_images_are_immutable_and_worker_waits_for_schema(self):
  import json
  lock=json.loads((ROOT/'infra/images.lock.json').read_text('utf-8'))
  self.assertFalse(lock['unresolved'])
  for name,service in self.config['services'].items():
   if not service['image'].startswith('talent-platform-'):
    self.assertRegex(service['image'],r'@sha256:[a-f0-9]{64}$',name)
  for path in [ROOT/'Dockerfile',ROOT/'infra/frontend.Dockerfile',ROOT/'infra/gateway.Dockerfile']:
   for image in re.findall(r'(?m)^FROM (\S+)',path.read_text('utf-8')):
    self.assertRegex(image,r'@sha256:[a-f0-9]{64}$')
  self.assertEqual(self.config['services']['worker']['depends_on']['api'],{'condition':'service_healthy'})
 def test_linux_entrypoints_and_templates_have_no_carriage_returns(self):
  for path in (ROOT/'infra').rglob('*'):
   if path.is_file() and path.suffix in {'.sh','.conf','.template'}:
    self.assertNotIn(b'\r',path.read_bytes(),str(path))
 def test_separate_redis_passwords_expand_inside_their_containers(self):
  for name in ['redis','dify-redis']:
   command=' '.join(self.config['services'][name]['entrypoint'])
   self.assertIn('--requirepass "$$REDIS_PASSWORD"',command)
  plugin=self.config['services']['dify-plugin-daemon']['environment']
  self.assertEqual(plugin['REDIS_PASSWORD'],'${DIFY_REDIS_PASSWORD}')
  self.assertEqual(plugin['REDIS_HOST'],'dify-redis')
 def test_frontend_resolves_recreated_api_and_accepts_declared_batch_limit(self):
  proxy=(ROOT/'infra/frontend.conf').read_text('utf-8')
  self.assertIn('resolver 127.0.0.11',proxy)
  self.assertIn('proxy_pass $platform_api',proxy)
  self.assertIn('client_max_body_size 4g',proxy)
if __name__=='__main__':unittest.main()
