"""Opt-in real bulk vector-seeding/matching benchmark, never import throughput.

Run inside the API container with the installed talent_platform package and its
production configuration. No Docker operations or collection creation/deletion.
An interrupted run leaves labelled synthetic rows with indexed_revision=0 until
their vectors have been flushed; reruns validate ownership and resume safely.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import math
import os
import platform
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

BENCHMARK = 'synthetic-talent-performance-v1'
NAMESPACE = uuid.UUID('8119ed51-d7c4-48b5-bb51-c01e82580bdd')
OUTPUT_ROOT = Path('/data/verification')


class UnsafeBenchmark(ValueError):
    pass


def validate_options(args):
    if not args.execute or not args.org_id or not args.actor_id:
        raise UnsafeBenchmark('Explicit --execute, --org-id and --actor-id are required')
    if not 1 <= args.count <= 10000 or args.batch_size not in {32, 64}:
        raise UnsafeBenchmark('Count must be 1..10000 and batch size 32 or 64')
    root, output = OUTPUT_ROOT.resolve(), Path(args.output).resolve()
    if not output.is_relative_to(root) or output == root or output.suffix != '.json':
        raise UnsafeBenchmark('Output must be a JSON file beneath /data/verification')
    return output


def validate_scope(org, actor, *, org_id, actor_id):
    if not org or org.get('id') != org_id or org.get('kind') != 'organizations':
        raise UnsafeBenchmark('Organization does not exist')
    name = str(org.get('data', {}).get('name', ''))
    if '合成' not in name and 'SYNTHETIC' not in name.upper():
        raise UnsafeBenchmark('Organization name must contain 合成 or SYNTHETIC')
    if (not actor or actor.get('id') != actor_id or actor.get('org_id') != org_id
            or actor.get('active') != 1 or actor.get('role') not in {'hr', 'admin'}):
        raise UnsafeBenchmark('Actor must be active same-organization hr/admin')


def benchmark_id(org_id, ordinal):
    return str(uuid.uuid5(NAMESPACE, f'{BENCHMARK}:{org_id}:{ordinal}'))


def record_spec(org_id, actor_id, ordinal):
    variant = ordinal % 10
    profile = {
        'name': f'合成性能人才{ordinal:05d}', 'source': 'manual', 'verified_by': actor_id,
        'location': '上海', 'skills': ['Java', 'SQL'] if variant == 7 else ['Python', 'SQL'],
        'education': [{'school': '合成大学', 'degree': '大专' if variant == 9 else '本科',
                       'start': '2016-09', 'end': '2020-06'}],
        'experiences': [{'company': '合成科技', 'role': 'Java工程师' if variant == 7 else 'Python工程师',
                         'description': '数据平台开发 SQL',
                         'start': '2023-01' if variant == 8 else '2020-01', 'end': '2024-01'}],
        'projects': [{'name': '合成数据平台', 'description': 'Python SQL 数据平台开发'}],
        'certificates': [], 'tags': ['合成', BENCHMARK],
    }
    return {'id': benchmark_id(org_id, ordinal), 'kind': 'talents', 'org_id': org_id,
            'owner_id': actor_id, 'revision': 1,
            'data': {'synthetic': True, 'benchmark': BENCHMARK, 'benchmark_ordinal': ordinal,
                     'profile': profile}}


def job_requirements():
    return {'required_skills': ['Python'], 'preferred_skills': ['SQL'],
            'min_experience_months': 24, 'min_education': '本科', 'location': '上海',
            'responsibilities': ['数据平台开发']}


def validate_record_collision(existing, expected):
    if existing is None:
        return
    if any(existing.get(key) != expected[key] for key in ('id', 'kind', 'org_id', 'owner_id', 'revision')):
        raise UnsafeBenchmark('Record ID collides with an unrelated or changed record')
    data = existing.get('data', {})
    if any(data.get(key) != value for key, value in expected['data'].items()):
        raise UnsafeBenchmark('Record ID collides with nonbenchmark or changed data')
    if data.get('deleted') or existing.get('indexed_revision', 0) not in {0, 1}:
        raise UnsafeBenchmark('Benchmark record is deleted or has unexpected index revision')


def profile_chunks(spec):
    from talent_platform.ai import split_documents
    text = json.dumps(spec['data']['profile'], ensure_ascii=False)
    return [part.page_content for part in split_documents(text)]


def vector_metadata(spec, chunk, model):
    return {'id': f'talent:{spec["id"]}:1:{chunk}', 'source_id': spec['id'],
            'source_path': f'talent/{spec["id"]}', 'chunk': chunk,
            'text': profile_chunks(spec)[chunk], 'kind': 'talent', 'org_id': spec['org_id'],
            'scope': 'org', 'owner_id': spec['owner_id'], 'revision': 1,
            'permission_version': 1, 'index_model': model, 'synthetic': True, 'benchmark': BENCHMARK}


def validate_vector_collision(existing, expected_by_id):
    expected = expected_by_id.get(str(existing.get('id')))
    if not expected or any(existing.get(key) != value for key, value in expected.items()):
        raise UnsafeBenchmark('Vector ID/source collides with nonbenchmark or changed metadata')


def validate_match_result(result, snapshots, requirements):
    from talent_platform.ai_domain import score_candidate
    candidates = result.get('candidates', [])
    if not 1 <= len(candidates) <= 20:
        raise UnsafeBenchmark('Match must return 1..20 candidates')
    diagnostics = result.get('diagnostics', {})
    if (diagnostics.get('authorized') != len(snapshots) or diagnostics.get('recall_limit') != 100
            or diagnostics.get('output_limit') != 20):
        raise UnsafeBenchmark('Match did not use the authorized 100-recall/20-output contract')
    by_id = {row['id']: row for row in snapshots}
    seen = set()
    for candidate in candidates:
        ident = candidate.get('talent_id')
        snapshot = by_id.get(ident)
        if not snapshot or ident in seen or candidate.get('revision') != 1:
            raise UnsafeBenchmark('Candidate is duplicated, unauthorized or stale')
        seen.add(ident)
        if candidate.get('profile') != snapshot['profile']:
            raise UnsafeBenchmark('Candidate profile differs from its authorized PG snapshot')
        score = candidate.get('score', {})
        evidence = score.get('evidence', [])
        if not evidence or any(hit.get('source_id') != ident or hit.get('org_id') != snapshot['org_id']
                               or hit.get('revision') != 1 or hit.get('index_model') != snapshot['index_model']
                               for hit in evidence):
            raise UnsafeBenchmark('Candidate evidence is outside the authorized indexed snapshot')
        recomputed = score_candidate(requirements, snapshot['profile'], evidence)
        if score != recomputed or not score['eligible'] or not all(c['status'] == 'pass' for c in score['conditions']):
            raise UnsafeBenchmark('Candidate failed deterministic score/hard-condition recomputation')
    expected_order = sorted(candidates, key=lambda candidate: (-candidate['score']['total'], candidate['talent_id']))
    if candidates != expected_order:
        raise UnsafeBenchmark('Match candidates are not deterministically ranked')


def memory_snapshot():
    snapshot = {'kind': 'point_in_time_not_peak', 'timestamp': datetime.now(timezone.utc).isoformat()}
    status = Path('/proc/self/status')
    if status.exists():
        for line in status.read_text().splitlines():
            key, _, value = line.partition(':')
            if key in {'VmRSS', 'VmSize', 'RssAnon', 'RssFile'}:
                snapshot[key + '_kib'] = int(value.strip().split()[0])
    for filename in ('memory.current', 'memory.max'):
        path = Path('/sys/fs/cgroup') / filename
        if path.exists():
            value = path.read_text().strip()
            snapshot['cgroup_' + filename.replace('.', '_') + '_bytes'] = int(value) if value.isdigit() else value
    return snapshot


def emit(event, **values):
    print(json.dumps({'event': event, **values}, ensure_ascii=False), flush=True)


def row_dict(row):
    return {key: getattr(row, key) for key in ('id', 'kind', 'org_id', 'owner_id', 'revision', 'indexed_revision', 'data')}


async def check_scope(stores, args):
    from talent_platform.db import Resource, User
    async with stores.business() as session:
        org, user = await session.get(Resource, args.org_id), await session.get(User, args.actor_id)
        org_value = {key: getattr(org, key) for key in ('id', 'kind', 'data')} if org else None
        actor = {key: getattr(user, key) for key in ('id', 'org_id', 'role', 'active')} if user else None
        validate_scope(org_value, actor, org_id=args.org_id, actor_id=args.actor_id)
        return actor


def preflight_vectors(index, specs):
    """Read all targeted sources/primary keys before any database/vector mutation."""
    client = index.client()
    try:
        if not client.has_collection(index.collection):
            raise UnsafeBenchmark('Existing talent_platform_documents_v2 collection is required')
        schema = client.describe_collection(index.collection)
        fields = {field['name']: field for field in schema.get('fields', [])}
        if not {'id', 'source_id', 'vector'} <= fields.keys() or not schema.get('enable_dynamic_field'):
            raise UnsafeBenchmark('Existing Milvus collection schema is incompatible')
        for offset in range(0, len(specs), 64):
            batch = specs[offset:offset + 64]
            expected = {row['id']: row for spec in batch for row in
                        [vector_metadata(spec, chunk, index.embedding_model) for chunk in range(len(profile_chunks(spec))) ]}
            expression = f'source_id in {json.dumps([spec["id"] for spec in batch])} or id in {json.dumps(list(expected))}'
            existing = client.query(index.collection, filter=expression, limit=16384,
                                    output_fields=list(next(iter(expected.values()))), consistency_level='Strong')
            if len(existing) >= 16384:
                raise UnsafeBenchmark('Collision preflight result reached its safety limit')
            for row in existing:
                validate_vector_collision(row, expected)
        return int(fields['vector']['params']['dim'])
    finally:
        client.close()


async def preflight_records(stores, specs):
    from sqlalchemy import select
    from talent_platform.db import Record
    expected = {spec['id']: spec for spec in specs}
    async with stores.facts() as session:
        for offset in range(0, len(specs), 500):
            ids = [spec['id'] for spec in specs[offset:offset + 500]]
            rows = (await session.scalars(select(Record).where(Record.id.in_(ids)))).all()
            for row in rows:
                validate_record_collision(row_dict(row), expected[row.id])


async def seed_records(stores, specs):
    from sqlalchemy import select
    from talent_platform.db import Record
    inserted = 0
    for offset in range(0, len(specs), 500):
        batch = specs[offset:offset + 500]
        async with stores.facts() as session:
            existing = {row.id: row for row in (await session.scalars(
                select(Record).where(Record.id.in_([spec['id'] for spec in batch])).with_for_update())).all()}
            for spec in batch:
                validate_record_collision(row_dict(existing[spec['id']]) if spec['id'] in existing else None, spec)
                if spec['id'] not in existing:
                    session.add(Record(**spec, indexed_revision=0))
                    inserted += 1
            await session.commit()
    return inserted


def commit_vectors(index, rows):
    client = index.client()
    try:
        expected = {row['id']: {key: value for key, value in row.items() if key != 'vector'} for row in rows}
        existing = client.query(index.collection, filter=f'id in {json.dumps(list(expected))}',
                                output_fields=list(next(iter(expected.values()))), limit=16384,
                                consistency_level='Strong')
        for row in existing:
            validate_vector_collision(row, expected)
        result = client.upsert(index.collection, rows)
        if int(result.get('upsert_count', -1)) != len(rows):
            raise UnsafeBenchmark('Milvus did not acknowledge every vector')
        client.flush(index.collection)
        written = client.query(index.collection, filter=f'id in {json.dumps(list(expected))}',
                               output_fields=list(next(iter(expected.values()))), limit=16384,
                               consistency_level='Strong')
        if len(written) != len(rows):
            raise UnsafeBenchmark('Flushed vectors could not all be read back')
        for row in written:
            validate_vector_collision(row, expected)
    finally:
        client.close()


async def mark_indexed(stores, specs, model):
    from sqlalchemy import select
    from talent_platform.db import Record
    expected = {spec['id']: spec for spec in specs}
    async with stores.facts() as session:
        rows = (await session.scalars(select(Record).where(Record.id.in_(expected)).with_for_update())).all()
        if len(rows) != len(specs):
            raise UnsafeBenchmark('Seeded talent disappeared before index acknowledgement')
        for row in rows:
            validate_record_collision(row_dict(row), expected[row.id])
            row.indexed_revision = 1
            row.data = {**row.data, 'index_model': model, 'index_source': 'real_batched_bge_gateway',
                        'benchmark_indexed_at': datetime.now(timezone.utc).isoformat()}
        await session.commit()


async def model_metadata(index):
    import httpx
    configured = {'embedding_model': index.embedding_model, 'chat_model': os.getenv('CHAT_MODEL', ''),
                  'embedding_model_digest': os.getenv('EMBEDDING_MODEL_DIGEST', ''),
                  'chat_model_digest': os.getenv('CHAT_MODEL_DIGEST', '')}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.get(index.embedding_url + '/api/tags')
            response.raise_for_status()
            tags = response.json().get('models', [])
            configured['installed'] = [{'name': row.get('name'), 'digest': row.get('digest'), 'size': row.get('size')}
                                       for row in tags]
    except Exception as exc:
        configured['tags_unavailable'] = type(exc).__name__
    return configured


async def run(args, report):
    from sqlalchemy import select
    from talent_platform.ai import AIPlatform, MilvusIndex
    from talent_platform.config import settings
    from talent_platform.db import Record, Stores
    config = settings()
    if not config.postgres_url.startswith('postgresql+') or not os.getenv('CHECKPOINT_DATABASE_URL', '').startswith(('postgresql://', 'postgres://')):
        raise UnsafeBenchmark('Real PostgreSQL facts and checkpoint databases are required')
    stores, index = Stores(config), MilvusIndex()
    try:
        actor = await check_scope(stores, args)
        if 'bge-m3' not in index.embedding_model.casefold():
            raise UnsafeBenchmark('Real BGE-M3 embeddings are required')
        specs = [record_spec(args.org_id, args.actor_id, ordinal) for ordinal in range(args.count)]
        await preflight_records(stores, specs)
        dimension = await asyncio.to_thread(preflight_vectors, index, specs)
        report['models'] = await model_metadata(index)
        report['runtime'] = {'python': sys.version.split()[0], 'platform': platform.platform(),
                             'application': __import__('talent_platform').__version__,
                             'packages': {name: importlib.metadata.version(name) for name in
                                          ('pymilvus', 'langgraph', 'langgraph-checkpoint-postgres')}}
        report['memory_before'] = memory_snapshot()
        started = time.perf_counter()
        report['inserted_records'] = await seed_records(stores, specs)
        report['seeding_seconds'] = round(time.perf_counter() - started, 6)
        report['embedding_seconds'] = report['vector_commit_seconds'] = 0.0
        vector_count = 0
        started = time.perf_counter()
        for offset in range(0, len(specs), args.batch_size):
            batch = specs[offset:offset + args.batch_size]
            rows = [vector_metadata(spec, chunk, index.embedding_model)
                    for spec in batch for chunk in range(len(profile_chunks(spec)))]
            embeddings = []
            tick = time.perf_counter()
            # Bound actual gateway input length even if future profiles span multiple chunks.
            for first in range(0, len(rows), args.batch_size):
                embeddings.extend(await index.embed([row['text'] for row in rows[first:first + args.batch_size]]))
            report['embedding_seconds'] += time.perf_counter() - tick
            if len(embeddings) != len(rows) or any(len(vector) != dimension or any(
                    isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                    for value in vector) for vector in embeddings):
                raise UnsafeBenchmark('Embedding response has invalid count, dimension or values')
            rows = [{**row, 'vector': vector} for row, vector in zip(rows, embeddings)]
            tick = time.perf_counter()
            await asyncio.to_thread(commit_vectors, index, rows)
            await mark_indexed(stores, batch, index.embedding_model)
            report['vector_commit_seconds'] += time.perf_counter() - tick
            vector_count += len(rows)
            if offset // args.batch_size % 10 == 0 or offset + len(batch) == len(specs):
                emit('index_progress', talents=min(offset + len(batch), len(specs)), total=len(specs), vectors=vector_count)
        report['embedding_index_seconds'] = round(time.perf_counter() - started, 6)
        report['embedding_seconds'] = round(report['embedding_seconds'], 6)
        report['vector_commit_seconds'] = round(report['vector_commit_seconds'], 6)
        report['vectors'] = vector_count
        await check_scope(stores, args)
        snapshots = []
        async with stores.facts() as session:
            for offset in range(0, len(specs), 500):
                expected = {spec['id']: spec for spec in specs[offset:offset + 500]}
                rows = (await session.scalars(select(Record).where(Record.id.in_(expected)))).all()
                for row in rows:
                    validate_record_collision(row_dict(row), expected[row.id])
                    if row.indexed_revision != 1 or row.data.get('index_model') != index.embedding_model:
                        raise UnsafeBenchmark('PG index snapshot is not current')
                    snapshots.append({'id': row.id, 'org_id': row.org_id, 'revision': row.revision,
                                      'indexed_revision': row.indexed_revision, 'index_model': row.data['index_model'],
                                      'profile': row.data['profile']})
        if len(snapshots) != args.count:
            raise UnsafeBenchmark('Authorized PG snapshot count differs from requested count')
        requirements = job_requirements()
        payload = {'job': {'id': benchmark_id(args.org_id, 'job'), 'org_id': args.org_id,
                            'title': '合成 Python 数据平台工程师', 'requirements': requirements, 'revision': 1},
                   'talents': snapshots, 'allowed_ids': [snapshot['id'] for snapshot in snapshots]}
        report['match_run_id'] = str(uuid.uuid4())
        tick = time.perf_counter()
        result = await AIPlatform(vectors=index).execute('match', payload, run_id=report['match_run_id'], actor=actor)
        report['match_seconds'] = round(time.perf_counter() - tick, 6)
        validate_match_result(result, snapshots, requirements)
        report.update(requirements=requirements, candidates=result['candidates'], diagnostics=result['diagnostics'],
                      versions=result.get('versions', {}), hard_conditions_all_pass=True, score_recomputed=True,
                      memory_after=memory_snapshot(), status='passed')
    finally:
        await stores.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--org-id', required=True)
    parser.add_argument('--actor-id', required=True)
    parser.add_argument('--count', type=int, default=10000)
    parser.add_argument('--batch-size', type=int, choices=(32, 64), default=64)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output', default='/data/verification/performance.json')
    args = parser.parse_args(argv)
    try:
        output = validate_options(args)
    except UnsafeBenchmark as exc:
        emit('refused', error=str(exc))
        return 2
    report = {'benchmark': BENCHMARK, 'synthetic': True, 'count': args.count, 'batch_size': args.batch_size,
              'org_id': args.org_id, 'actor_id': args.actor_id, 'status': 'started',
              'started_at': datetime.now(timezone.utc).isoformat(),
              'measurement_scope': 'real_bulk_pg_vector_seed_and_match; NOT production resume import throughput',
              'bypasses': ['resume/file parsing', 'OCR', 'LLM profile extraction', 'individual worker index jobs'],
              'checkpoint_backend': 'real PostgreSQL via AIPlatform.execute',
              'memory_limitations': 'before/after container/process snapshots; GPU and peak sampling are external'}
    emit('started', count=args.count, batch_size=args.batch_size, benchmark=BENCHMARK)
    code = 0
    try:
        asyncio.run(run(args, report))
    except Exception as exc:
        # SQL/HTTP exceptions can contain URLs or credentials: only safe refusal messages are exposed.
        report.update(status='failed', error_type=type(exc).__name__)
        if isinstance(exc, UnsafeBenchmark):
            report['error'] = str(exc)
        report['memory_after'] = memory_snapshot()
        code = 1
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(output)
    except OSError as exc:
        emit('report_write_failed', error_type=type(exc).__name__)
        return 1
    emit('finished', status=report['status'], output=str(output), count=args.count,
         candidates=len(report.get('candidates', [])), seeding_seconds=report.get('seeding_seconds'),
         embedding_index_seconds=report.get('embedding_index_seconds'), match_seconds=report.get('match_seconds'),
         error_type=report.get('error_type'), error=report.get('error'))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
