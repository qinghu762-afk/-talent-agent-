from pathlib import Path
p=Path(__file__).parent/'test_infra_safety.py';s=p.read_text('utf-8-sig');needle='    def test_bootstrap_only_accepts_new_local_dify(self):'
s=s.replace(needle,"""    def test_archive_rejects_duplicate_paths_after_link(self):
        path=Path(__file__).parent/'validate_archive.py'
        spec=importlib.util.spec_from_file_location('archive_safety',path)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            archive=Path(d)/'duplicate.tar.gz'
            with tarfile.open(archive,'w:gz') as t:
                info=tarfile.TarInfo('./python');info.type=tarfile.SYMTYPE;info.linkname='/usr/local/bin/python3.12';t.addfile(info)
                t.addfile(tarfile.TarInfo('./python'))
            with self.assertRaises(ValueError):mod.validate(archive)

"""+needle);p.write_text(s,encoding='utf-8')
