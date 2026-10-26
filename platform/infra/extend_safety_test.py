from pathlib import Path
p=Path(__file__).parent/'test_infra_safety.py'
s=p.read_text('utf-8-sig')
needle='    def test_bootstrap_only_accepts_new_local_dify(self):'
test='''    def test_archive_accepts_runtime_python_links_but_rejects_children(self):
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

'''
s=s.replace(needle,test+needle);p.write_text(s,encoding='utf-8')
