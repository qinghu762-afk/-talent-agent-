import importlib.util
from pathlib import Path
import io
import tarfile
import tempfile
import unittest

class InfraSafety(unittest.TestCase):
    def test_archive_rejects_traversal_links_and_devices(self):
        path=Path(__file__).parent/'validate_archive.py'
        self.assertTrue(path.exists(), 'archive validator must exist')
        spec=importlib.util.spec_from_file_location('archive_safety',path)
        mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        for name,kind in [('../escape',tarfile.REGTYPE),('/absolute',tarfile.REGTYPE),('./link',tarfile.SYMTYPE),('./device',tarfile.CHRTYPE)]:
            with tempfile.TemporaryDirectory() as d:
                archive=Path(d)/'test.tar.gz'
                with tarfile.open(archive,'w:gz') as t:
                    info=tarfile.TarInfo(name);info.type=kind;t.addfile(info)
                with self.assertRaises(ValueError):mod.validate(archive)

    def test_archive_accepts_runtime_python_links_but_rejects_children(self):
        path=Path(__file__).parent/'validate_archive.py'
        spec=importlib.util.spec_from_file_location('archive_safety',path)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            archive=Path(d)/'venv.tar.gz'
            with tarfile.open(archive,'w:gz') as t:
                info=tarfile.TarInfo('./.venv/bin/python');info.type=tarfile.SYMTYPE;info.linkname='/usr/local/bin/python3.12';t.addfile(info)
            self.assertTrue(mod.validate(archive))
            with tarfile.open(archive,'w:gz') as t:
                info=tarfile.TarInfo('./.venv/bin/python');info.type=tarfile.SYMTYPE;info.linkname='/usr/local/bin/python3.12';t.addfile(info)
                t.addfile(tarfile.TarInfo('./.venv/bin/python/escape'))
            with self.assertRaises(ValueError):mod.validate(archive)

    def test_archive_rejects_duplicate_paths_after_link(self):
        path=Path(__file__).parent/'validate_archive.py'
        spec=importlib.util.spec_from_file_location('archive_safety',path)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            archive=Path(d)/'duplicate.tar.gz'
            with tarfile.open(archive,'w:gz') as t:
                info=tarfile.TarInfo('./python');info.type=tarfile.SYMTYPE;info.linkname='/usr/local/bin/python3.12';t.addfile(info)
                t.addfile(tarfile.TarInfo('./python'))
            with self.assertRaises(ValueError):mod.validate(archive)

    def test_bootstrap_only_accepts_new_local_dify(self):
        path=Path(__file__).parent/'bootstrap_dify.py'
        self.assertTrue(path.exists(),'Dify bootstrap must exist')
        spec=importlib.util.spec_from_file_location('bootstrap_safety',path)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        for url in ['http://127.0.0.1:8080','http://localhost:18081','https://example.com','http://127.0.0.1:18081@evil.com']:
            with self.assertRaises(ValueError):mod.validate_target(url)
        self.assertEqual(mod.validate_target('http://127.0.0.1:18081'),'http://127.0.0.1:18081')
        paths=mod.skills_schema()['paths']
        self.assertIn('/api/v1/integrations/dify/runs/{run_id}',paths)
        workflow=mod.workflow_dsl('qwen3:4b')
        self.assertEqual(workflow['app']['mode'],'workflow')
        self.assertIn('prompt',str(workflow))
        self.assertIn('text',str(workflow))
        llm=next(node['data'] for node in workflow['workflow']['graph']['nodes'] if node['id']=='llm')
        self.assertIs(llm['model']['completion_params']['think'],False)
        self.assertEqual(llm['model']['completion_params']['format'],'json')
        import json
        from jsonschema import validate, ValidationError
        schema=json.loads(llm['model']['completion_params']['json_schema'])
        with self.assertRaises(ValidationError):
            validate({'profile':{'skills':[{'value':'Python'}],'evidence':[]}},schema)
        with self.assertRaises(ValidationError):
            validate({'requirements':{'evidence':[{'field':'required_skills','quote':'Python'}]}},schema)

    def test_pinned_official_plugin_and_no_reuse_of_masked_keys(self):
        path=Path(__file__).parent/'bootstrap_dify.py'
        spec=importlib.util.spec_from_file_location('bootstrap_safety',path)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        package=Path(__file__).parent/'dify/ollama.difypkg'
        self.assertTrue(mod.validate_plugin(package).startswith('langgenius/ollama:1.0.2@'))
        instance=object.__new__(mod.Bootstrap)
        instance.values={'DIFY_APP_ID':'test-workflow','DIFY_DATASET_KEY':'dataset-present','CHAT_MODEL':'qwen3:4b'}
        calls=[]
        def call(method,path,**kwargs):
            calls.append((method,path))
            return {'token':'full-reveal-once-token'} if path.endswith('/api-keys') else {}
        instance.call=call
        instance.save=lambda **values:instance.values.update(values)
        instance.application()
        self.assertEqual(instance.values['DIFY_APP_KEY'],'full-reveal-once-token')
        self.assertNotIn(('GET','/apps/test-workflow/api-keys'),calls)
        self.assertIn(('POST','/apps/test-workflow/workflows/draft'),calls)

if __name__=='__main__':unittest.main()
