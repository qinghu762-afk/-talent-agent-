"""Pure restore safety checks. Never contacts a real Docker engine."""
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def helper():
    path = ROOT / 'tools' / 'verify_restore_clone.py'
    assert path.exists(), 'The isolated restore helper must exist'
    spec = importlib.util.spec_from_file_location('restore_clone', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RestoreCloneSafety(unittest.TestCase):
    def fixture(self, root, member='./payload'):
        module = helper()
        source = root / 'snapshot'
        source.mkdir()
        files = {}
        for volume in module.VOLUMES:
            path = source / (volume + '.tar.gz')
            with tarfile.open(path, 'w:gz') as archive:
                entry = tarfile.TarInfo(member)
                entry.size = 4
                archive.addfile(entry, io.BytesIO(b'data'))
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        config = source / 'config.env'
        config.write_text('POSTGRES_PASSWORD=private\n', encoding='utf-8')
        files[config.name] = hashlib.sha256(config.read_bytes()).hexdigest()
        manifest = dict(schema=1, project='talent-platform', engine_id='engine-one',
                        volumes=list(module.VOLUMES), files=files)
        (source / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        return module, source, manifest

    def test_validates_all_archives_and_config_hash(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'verification', ignore_cleanup_errors=True) as directory:
            module, source, manifest = self.fixture(Path(directory))
            self.assertEqual(module.validate_backup(source, 'engine-one')['files'], manifest['files'])
            (source / 'config.env').write_text('changed', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                module.validate_backup(source, 'engine-one')

    def test_rejects_foreign_project_engine_and_manifest_traversal(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'verification', ignore_cleanup_errors=True) as directory:
            module, source, manifest = self.fixture(Path(directory))
            for key, value in [('project', 'legacy'), ('engine_id', 'foreign'), ('schema', 2),
                               ('files', {'../escape': '0' * 64})]:
                bad = dict(manifest, **{key: value})
                (source / 'manifest.json').write_text(json.dumps(bad), encoding='utf-8')
                with self.subTest(key=key), self.assertRaises(ValueError):
                    module.validate_backup(source, 'engine-one')

    def test_rejects_archive_member_traversal_before_docker(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'verification', ignore_cleanup_errors=True) as directory:
            module, source, _ = self.fixture(Path(directory), '../outside')
            with self.assertRaisesRegex(ValueError, 'archive'):
                module.validate_backup(source, 'engine-one')

    def test_clone_compose_has_only_stores_no_ports_or_original_mounts(self):
        module = helper()
        project = 'talent-platform-restorecheck-20261022T010203Z-a1b2c3d4e5f6'
        compose = module.build_clone_compose(ROOT / 'compose.yaml', project)
        self.assertEqual(set(compose['services']), {'postgres', 'mysql', 'redis', 'etcd', 'minio', 'milvus'})
        self.assertEqual(len(compose['volumes']), 14)
        for service in compose['services'].values():
            self.assertNotIn('ports', service)
            self.assertNotIn('build', service)
            self.assertEqual(service['restart'], 'no')
            self.assertRegex(service['image'], r'@sha256:[0-9a-f]{64}$')
            for mount in service['volumes']:
                self.assertEqual(mount['type'], 'volume')
                self.assertIn(mount['source'], compose['volumes'])
                self.assertNotIn('initdb', mount['target'])
        for volume in compose['volumes'].values():
            self.assertTrue(volume['name'].startswith(project + '_'))
            self.assertNotIn('external', volume)
        self.assertEqual(set(compose['networks']), {'data'})
        self.assertTrue(compose['networks']['data']['internal'])

    def test_rejects_reusing_namespace_before_creating_anything(self):
        module = helper()
        project = 'talent-platform-restorecheck-20261022T010203Z-a1b2c3d4e5f6'
        for resource in ('volume', 'container', 'network'):
            class Docker:
                def call(self, args, **kwargs):
                    if args[0] == resource:
                        return project + '_postgres\n'
                    return ''
            with self.subTest(resource=resource), self.assertRaisesRegex(ValueError, 'exists'):
                module.assert_fresh_namespace(Docker(), project)

    def test_engine_change_blocks_mutation_and_does_not_dump_output(self):
        module = helper()
        with tempfile.TemporaryDirectory(dir=ROOT / 'verification', ignore_cleanup_errors=True) as directory:
            marker = Path(directory) / '.docker-runtime.json'
            marker.write_text(json.dumps({'schema': 1, 'engine_id': 'engine-one'}), encoding='utf-8')
            docker = module.Docker(marker)
            commands = []
            def run(args, **kwargs):
                commands.append(args)
                return subprocess.CompletedProcess(args, 0, 'engine-other\n', 'secret')
            with patch.object(module.subprocess, 'run', side_effect=run):
                with self.assertRaisesRegex(ValueError, 'engine identity'):
                    docker.call(['volume', 'create', 'never-create'])
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][1], 'info')

    def test_file_comparison_failure_never_starts_stores(self):
        self.exercise_files_only(fail_comparison=True)

    def test_files_only_compares_all_fourteen_without_starting_stores(self):
        self.exercise_files_only(fail_comparison=False)

    def test_full_run_queries_stores_then_stops_only_generated_clone(self):
        self.exercise_files_only(fail_comparison=False, stores=True)

    def test_failed_store_query_still_stops_only_clone(self):
        self.exercise_files_only(fail_comparison=False, stores=True, fail_query=True)

    def exercise_files_only(self, fail_comparison, stores=False, fail_query=False):
        module = helper()
        with tempfile.TemporaryDirectory(dir=ROOT / 'verification', ignore_cleanup_errors=True) as directory:
            platform = Path(directory) / 'platform'
            platform.mkdir()
            (platform / 'infra').mkdir()
            shutil.copyfile(ROOT / 'compose.yaml', platform / 'compose.yaml')
            shutil.copyfile(ROOT / 'infra' / 'validate_archive.py', platform / 'infra' / 'validate_archive.py')
            _, source, _ = self.fixture(platform)
            commands = []
            labels = {}
            class FakeDocker:
                def __init__(self, marker):
                    self.engine_id = 'engine-one'
                    self.environment = {}

                def call(self, args, **kwargs):
                    commands.append(args)
                    if args[:2] == ['volume', 'create']:
                        labels[args[-1]] = dict(item.split('=', 1) for index, item in enumerate(args)
                                              if index and args[index - 1] == '--label')
                    if args[:2] == ['volume', 'inspect']:
                        return json.dumps([{'Name': args[-1], 'Labels': labels[args[-1]]}])
                    if 'tar' in args and '-dzf' in args and fail_comparison:
                        raise ValueError('File comparison failed')
                    if args[0] == 'compose' and 'ps' in args:
                        return '\n'.join(['clone-' + name for name in module.STORES])
                    if args[:2] == ['container', 'inspect']:
                        return json.dumps([{'State': {'Status': 'running', 'Health': {'Status': 'healthy'}}}
                                           for _ in module.STORES])
                    if module.COUNT_SCRIPT in args:
                        if fail_query:
                            raise ValueError('Clone count query failed')
                        return json.dumps({'postgres.talent_analytics.records': 7, 'mysql.users': 2,
                                           'redis.keys': 3, 'milvus.rows': 9})
                    return ''
            module.ROOT = platform
            with patch.object(module, 'Docker', FakeDocker):
                if fail_comparison or fail_query:
                    with self.assertRaisesRegex(ValueError, 'comparison|query'):
                        module.execute(source)
                else:
                    result = module.execute(source, files_only=not stores)
                    self.assertEqual(result['status'], 'passed')
                    self.assertEqual(len(result['file_checks']), 14)
                    if stores:
                        self.assertEqual(result['counts']['milvus.rows'], 9)
            if stores:
                stopped = [command for command in commands if command[0] == 'compose' and 'stop' in command]
                self.assertEqual(len(stopped), 1)
                self.assertTrue(stopped[0][2].startswith('talent-platform-restorecheck-'))
                self.assertEqual(stopped[0][-6:], list(module.STORES))
                start_index = next(index for index, command in enumerate(commands) if 'up' in command)
                self.assertEqual(sum('-dzf' in command for command in commands[:start_index]), 14)
            else:
                self.assertFalse(any(command[0] == 'compose' for command in commands))
            self.assertFalse(any(command[0] in ('rm', 'prune', 'down') for command in commands))
            created = [command[-1] for command in commands if command[:2] == ['volume', 'create']]
            self.assertTrue(all(name.startswith('talent-platform-restorecheck-') for name in created))
            self.assertFalse(any(name.startswith('talent-platform_') for name in created))
            comparisons = [command for command in commands if 'tar' in command and '-dzf' in command]
            self.assertEqual(len(comparisons), 1 if fail_comparison else 14)


if __name__ == '__main__':
    unittest.main()
