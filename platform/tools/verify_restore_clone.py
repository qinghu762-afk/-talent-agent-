"""Verify a cold backup in fresh isolated stores; never deletes Docker resources.

Usage: python platform/tools/verify_restore_clone.py --backup platform/backups/platform-TIMESTAMP
Requires local Python with PyYAML, original immutable images, and talent-platform-api:0.2.0.
The default performs file comparison AND real store count reads; --files-only skips store launch.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('postgres', 'mysql', 'redis', 'etcd', 'minio', 'milvus', 'app-data',
         'dify-redis', 'dify-storage', 'dify-sandbox-deps', 'dify-sandbox-conf',
         'dify-plugins', 'dify-agent-home', 'dify-agent-workspace')
VOLUMES = tuple('talent-platform_' + name for name in NAMES)
STORES = ('postgres', 'mysql', 'redis', 'etcd', 'minio', 'milvus')
PROJECT_RE = re.compile(r'talent-platform-restorecheck-\d{8}T\d{6}Z-[a-f0-9]{12}\Z')
HASH_RE = re.compile(r'[a-f0-9]{64}\Z')


def safe_path(path: Path, parent: Path) -> Path:
    """Reject traversal, links, junctions and paths outside an expected root."""
    path = Path(os.path.abspath(path))
    parent = parent.resolve()
    if not path.is_relative_to(parent):
        raise ValueError('Path is outside the new platform directory')
    current = path
    while current != parent.parent:
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('Linked deployment paths are forbidden')
        current = current.parent
    return path


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON keys')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=pairs)


def validate_backup(source: Path, engine_id: str):
    manifest = read_json(source / 'manifest.json')
    if (type(manifest.get('schema')) is not int or manifest['schema'] != 1
            or manifest.get('project') != 'talent-platform'
            or manifest.get('engine_id') != engine_id):
        raise ValueError('Backup schema, project or engine identity mismatch')
    volumes = manifest.get('volumes')
    if not isinstance(volumes, list) or len(volumes) != 14 or set(volumes) != set(VOLUMES):
        raise ValueError('Backup volume set mismatch')
    expected = {'config.env', *(volume + '.tar.gz' for volume in VOLUMES)}
    files = manifest.get('files')
    if not isinstance(files, dict) or set(files) != expected:
        raise ValueError('Unsafe or missing backup manifest filename')
    for filename, expected_hash in files.items():
        path = safe_path(source / filename, source)
        if not isinstance(expected_hash, str) or not HASH_RE.fullmatch(expected_hash):
            raise ValueError('Invalid backup checksum')
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected_hash:
            raise ValueError('Backup checksum mismatch')
    spec = importlib.util.spec_from_file_location('platform_archive_validator', ROOT / 'infra' / 'validate_archive.py')
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    for volume in VOLUMES:
        try:
            validator.validate(source / (volume + '.tar.gz'))
        except (ValueError, OSError) as error:
            raise ValueError('Unsafe or unreadable backup archive') from error
    return manifest


class Docker:
    """Every Docker operation is preceded by a fresh preserved-engine check."""
    def __init__(self, marker: Path):
        self.marker = marker
        data = read_json(marker)
        if data.get('schema') != 1 or not isinstance(data.get('engine_id'), str) or not data['engine_id']:
            raise ValueError('Preserved Docker engine identity marker is invalid')
        self.engine_id = data['engine_id']
        self.environment = dict(os.environ)

    def raw(self, args, timeout=180, input=None):
        try:
            result = subprocess.run(['docker', *args], capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=timeout,
                                    input=input, env=self.environment, shell=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError('Docker operation unavailable or timed out') from error
        if result.returncode:
            # Docker errors can include interpolated passwords. Never replay stderr/stdout.
            raise ValueError('Docker operation failed; private output suppressed')
        return result.stdout.strip()

    def call(self, args, **kwargs):
        marker = read_json(self.marker)
        actual = self.raw(['info', '--format', '{{.ID}}'], timeout=30)
        if marker.get('schema') != 1 or marker.get('engine_id') != self.engine_id or actual != self.engine_id:
            raise ValueError('Docker engine identity changed; operation refused')
        return self.raw(args, **kwargs)


def assert_project(project):
    if not PROJECT_RE.fullmatch(project):
        raise ValueError('Invalid generated clone namespace')


def assert_fresh_namespace(docker, project):
    assert_project(project)
    for resource, args in (
            ('volume', ['volume', 'ls', '--format', '{{.Name}}']),
            ('container', ['container', 'ls', '-a', '--format', '{{.Names}}']),
            ('network', ['network', 'ls', '--format', '{{.Name}}'])):
        names = docker.call(args).splitlines()
        if any(name.startswith(project) for name in names):
            raise ValueError('Clone namespace already exists: ' + resource)
    # Labels also catch manually renamed containers/networks in the same project.
    for resource in ('container', 'volume', 'network'):
        args = [resource, 'ls'] + (['-a'] if resource == 'container' else [])
        if docker.call([*args, '--filter', 'label=com.docker.compose.project=' + project, '-q']):
            raise ValueError('Clone project label already exists')


def build_clone_compose(compose_path, project):
    import yaml
    assert_project(project)
    original = yaml.safe_load(Path(compose_path).read_text(encoding='utf-8'))
    clone = {'name': project, 'services': {}, 'networks': {'data': {'internal': True,
             'name': project + '_data'}}, 'volumes': {}}
    for name in NAMES:
        clone['volumes'][name] = {'name': project + '_' + name,
                                 'labels': {'com.docker.compose.project': project}}
    # Whitelist fields rather than trying to remove every possible unsafe option.
    for name in STORES:
        source = original['services'][name]
        if not re.search(r'@sha256:[a-f0-9]{64}\Z', source['image']):
            raise ValueError('Store images must use pinned existing digests')
        service = {key: copy.deepcopy(source[key]) for key in
                   ('image', 'environment', 'command', 'entrypoint', 'healthcheck', 'security_opt') if key in source}
        service.update(restart='no', networks=['data'], volumes=[])
        for mount in source.get('volumes', []):
            if not isinstance(mount, str):
                raise ValueError('Unexpected original store mount format')
            parts = mount.split(':')
            if parts[0] == name:
                service['volumes'].append({'type': 'volume', 'source': name, 'target': parts[1],
                                           'volume': {'nocopy': True}})
            elif '/docker-entrypoint-initdb.d/' not in mount or not parts[0].startswith('./infra/'):
                raise ValueError('Unexpected original store bind mount')
        if len(service['volumes']) != 1:
            raise ValueError('Each clone store must have exactly one cloned volume')
        if name == 'milvus':
            service['depends_on'] = {dep: {'condition': 'service_healthy'} for dep in ('etcd', 'minio')}
        clone['services'][name] = service
    return clone


COUNT_SCRIPT = r'''
import json, logging, os
logging.disable(logging.CRITICAL)
import psycopg, pymysql, redis
from pymilvus import MilvusClient
counts = {}
for database, tables in [('talent_analytics', ('records', 'runs')),
                          ('talent_checkpoint', ('checkpoints',)), ('dify', ('apps',))]:
    with psycopg.connect(host='postgres', dbname=database, user='postgres',
                          password=os.environ['POSTGRES_PASSWORD'], connect_timeout=15,
                          options='-c default_transaction_read_only=on -c statement_timeout=30000') as connection:
        for table in tables:
            with connection.cursor() as cursor:
                cursor.execute('SELECT count(*) FROM ' + table)
                counts['postgres.' + database + '.' + table] = cursor.fetchone()[0]
connection = pymysql.connect(host='mysql', user='root', password=os.environ['MYSQL_ROOT_PASSWORD'],
                            database='talent', connect_timeout=15, read_timeout=30)
try:
    with connection.cursor() as cursor:
        cursor.execute('SET SESSION TRANSACTION READ ONLY')
        cursor.execute('START TRANSACTION READ ONLY')
        for table in ('users', 'resources'):
            cursor.execute('SELECT count(*) FROM ' + table)
            counts['mysql.' + table] = cursor.fetchone()[0]
finally:
    connection.rollback()
    connection.close()
client = redis.Redis(host='redis', password=os.environ['REDIS_PASSWORD'], socket_timeout=15)
counts['redis.keys'] = client.dbsize()
client.close()
client = MilvusClient(uri='http://milvus:19530', timeout=30)
try:
    databases = client.list_databases(timeout=30)
    counts['milvus.databases'] = len(databases)
    total = collections = 0
    for database in databases:
        client.use_database(database)
        names = sorted(client.list_collections(timeout=30))
        for name in names:
            stats = client.get_collection_stats(collection_name=name, timeout=30)
            rows = int(stats['row_count'])
            counts['milvus.collection_' + str(collections) + '.row_count'] = rows
            total += rows
            collections += 1
    counts['milvus.collections'] = collections
    counts['milvus.rows'] = total
finally:
    client.close()
print(json.dumps(counts, sort_keys=True))
'''


def inspect_owned_volume(docker, target, project, nonce):
    data = json.loads(docker.call(['volume', 'inspect', target]))
    if len(data) != 1 or data[0].get('Name') != target:
        raise ValueError('Clone volume identity mismatch')
    labels = data[0].get('Labels') or {}
    if labels.get('com.docker.compose.project') != project or labels.get('talent.restorecheck.nonce') != nonce:
        raise ValueError('Clone volume ownership mismatch')


def wait_healthy(docker, compose_args, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ids = docker.call([*compose_args, 'ps', '-a', '-q']).splitlines()
        if ids:
            state = json.loads(docker.call(['container', 'inspect', *ids]))
            if any(item['State'].get('Status') in ('exited', 'dead') or
                   item['State'].get('Health', {}).get('Status') == 'unhealthy' for item in state):
                raise ValueError('A cloned store failed health validation')
            if len(state) == len(STORES) and all(
                    item['State'].get('Health', {}).get('Status') == 'healthy' for item in state):
                return
        time.sleep(3)
    raise ValueError('Cloned store health deadline exceeded')


def execute(source, files_only=False, health_timeout=600):
    source = safe_path(source, ROOT)
    docker = Docker(ROOT.parent / '.docker-runtime.json')
    validate_backup(source, docker.engine_id)
    project = 'talent-platform-restorecheck-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + secrets.token_hex(6)
    nonce = secrets.token_hex(16)
    compose = build_clone_compose(ROOT / 'compose.yaml', project)
    # Compose env-file must win over ambient shell variables, without logging secrets.
    interpolated = set(re.findall(r'\$\{([A-Za-z_][A-Za-z0-9_]*)', json.dumps(compose)))
    docker.environment = {key: value for key, value in docker.environment.items()
                          if key not in interpolated and not key.startswith('COMPOSE_')}
    assert_fresh_namespace(docker, project)
    tool_image = compose['services']['postgres']['image']
    docker.call(['image', 'inspect', tool_image])
    docker.call(['image', 'inspect', 'talent-platform-api:0.2.0'])
    folder = safe_path(ROOT / 'verification' / project, ROOT)
    folder.mkdir(parents=True, exist_ok=False)
    compose_file = folder / 'compose.json'
    compose_file.write_text(json.dumps(compose, indent=2), encoding='utf-8')
    args = ['compose', '--project-name', project, '--project-directory', str(folder),
            '--env-file', str(source / 'config.env'), '-f', str(compose_file)]
    report = {'schema': 1, 'project': project, 'source_project': 'talent-platform',
              'engine_id': docker.engine_id, 'mode': 'files-only' if files_only else 'stores',
              'file_checks': {}, 'counts': {}, 'status': 'in-progress', 'containers_stopped': False,
              'retained_volumes': []}
    launched = False
    try:
        for name, original in zip(NAMES, VOLUMES):
            target = project + '_' + name
            # Check again immediately before each creation; never use existing volume data.
            if target in docker.call(['volume', 'ls', '--format', '{{.Name}}']).splitlines():
                raise ValueError('Clone target volume already exists')
            docker.call(['volume', 'create', '--label', 'com.docker.compose.project=' + project,
                         '--label', 'com.docker.compose.volume=' + name,
                         '--label', 'talent.restorecheck.nonce=' + nonce, target])
            report['retained_volumes'].append(target)
            inspect_owned_volume(docker, target, project, nonce)
            mount = 'type=volume,source=' + target + ',target=/snapshot,volume-nocopy'
            base = ['run', '--rm', '--pull', 'never', '--network', 'none', '--label',
                    'com.docker.compose.project=' + project, '--mount', mount]
            if docker.call([*base, tool_image, 'find', '/snapshot', '-mindepth', '1', '-print', '-quit']):
                raise ValueError('Clone target volume is populated')
            archive_mount = 'type=bind,source=' + str(source) + ',target=/backup,readonly'
            archive = '/backup/' + original + '.tar.gz'
            inspect_owned_volume(docker, target, project, nonce)
            docker.call([*base, '--mount', archive_mount, tool_image, 'tar', '-xzf', archive, '-C', '/snapshot'], timeout=1800)
            docker.call([*base, '--mount', archive_mount, tool_image, 'tar', '-dzf', archive, '-C', '/snapshot'], timeout=1800)
            report['file_checks'][original] = 'tar-compare-passed'
        # All 14 archives are compared before any DB container can start.
        if not files_only:
            for name in STORES:
                docker.call(['image', 'inspect', compose['services'][name]['image']])
            launched = True
            docker.call([*args, 'up', '-d', '--no-build', '--pull', 'never', '--wait',
                         '--wait-timeout', str(health_timeout), *STORES], timeout=health_timeout + 60)
            wait_healthy(docker, args, health_timeout)
            output = docker.call(['run', '--rm', '--pull', 'never', '--network', project + '_data',
                                  '--label', 'com.docker.compose.project=' + project,
                                  '--env-file', str(source / 'config.env'), '--entrypoint', 'python',
                                  'talent-platform-api:0.2.0', '-c', COUNT_SCRIPT], timeout=300)
            counts = json.loads(output)
            if not counts or not all(isinstance(key, str) and type(value) is int and value >= 0
                                     for key, value in counts.items()):
                raise ValueError('Store verifier returned invalid counts')
            report['counts'] = counts
        report['status'] = 'passed'
    except (ValueError, OSError) as error:
        report['status'] = 'failed'
        report['error'] = str(error) if isinstance(error, ValueError) else 'Local file operation failed'
        raise
    finally:
        try:
            if launched:
                # Explicit service allowlist: never stop parent containers, remove, down or prune.
                docker.call([*args, 'stop', '-t', '120', *STORES], timeout=180)
            report['containers_stopped'] = True
        except ValueError:
            report['containers_stopped'] = False
            report['status'] = 'failed'
            report['stop_error'] = 'Could not stop clone stores; original engine check still enforced'
        report['completed_utc'] = datetime.now(timezone.utc).isoformat()
        destination = safe_path(ROOT / 'verification' / 'restore-check.json', ROOT)
        destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
        (folder / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not report['containers_stopped']:
        raise ValueError('Clone store shutdown could not be verified')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True, type=Path)
    parser.add_argument('--files-only', action='store_true')
    parser.add_argument('--health-timeout', type=int, default=600)
    options = parser.parse_args()
    if not 30 <= options.health_timeout <= 1800:
        parser.error('--health-timeout must be between 30 and 1800 seconds')
    try:
        report = execute(options.backup, options.files_only, options.health_timeout)
    except Exception:
        # Even parser/driver exceptions may embed connection strings; suppress raw detail.
        print('Restore validation failed; inspect the sanitized restore-check report if created.', file=sys.stderr)
        return 1
    print(json.dumps({'project': report['project'], 'status': report['status'],
                      'compared_volumes': len(report['file_checks']), 'counts': report['counts']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
