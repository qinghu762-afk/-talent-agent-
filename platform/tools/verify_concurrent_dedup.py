"""Exercise real PostgreSQL identity/hash transactions; no model substitutes claimed."""
import asyncio
import hashlib
import json
import uuid
from pathlib import Path
from sqlalchemy import select, func
from talent_platform.worker import Worker
from talent_platform.db import User, Resource, Document, Record
from talent_platform.persistence import persist_resume
from talent_platform.uploads import save_file
from talent_platform.security import resolved_user


async def main():
    worker = Worker()
    try:
        actor_id = '51cfa6c6-6b9c-4318-8deb-d0a7c4443643'
        async with worker.stores.business() as db:
            user = await db.get(User, actor_id)
            org = await db.get(Resource, user.org_id)
            assert user.active and user.role == 'hr' and org.data.get('synthetic')
            who = await resolved_user(db, user)
        suffix = uuid.uuid4().hex[:12]
        text = '合成并发事务测试 ' + suffix
        def source(content):
            digest, path = save_file(worker.config.data_dir, 'synthetic-concurrent.txt', content.encode())
            return {'sha256': digest, 'path': path, 'filename': 'synthetic-concurrent.txt'}
        first = source(text)
        profile = {'source': 'manual', 'verified_by': actor_id, 'name': '合成并发' + suffix,
                   'email': 'concurrency-' + suffix + '@example.test', 'skills': ['Python'], 'education': [{'degree': '本科'}]}
        result = {'profile': profile, 'report': {'quality_status': 'complete', 'missing_fields': [],
                    'retry_count': 0, 'stop_reason': 'synthetic_database_transaction_test',
                    'input_sha256': hashlib.sha256(text.encode()).hexdigest()}}
        same = await asyncio.gather(*[persist_resume(worker.stores, who, first, result) for _ in range(8)])
        assert len({item['talent_id'] for item in same}) == len({item['document_id'] for item in same}) == 1
        assert sum(not item['reused'] for item in same) == 1
        versions = [source(text + '\n合成版本 ' + str(i)) for i in range(3)]
        merged = await asyncio.gather(*[persist_resume(worker.stores, who, item, result) for item in versions])
        assert {item['talent_id'] for item in merged} == {same[0]['talent_id']}
        assert len({item['merge_id'] for item in merged}) == 3
        async with worker.stores.facts() as db:
            count = await db.scalar(select(func.count()).select_from(Document).where(Document.org_id == who['org_id'],
                                Document.sha256.in_([first['sha256']] + [s['sha256'] for s in versions])))
            talent = await db.get(Record, same[0]['talent_id'])
            assert count == 4 and talent.revision == 4
        report = {'passed': True, 'synthetic': True, 'scope': 'real PostgreSQL transaction/locking only; no model inference',
                  'same_hash_requests': 8, 'same_hash_documents': 1, 'same_identity_versions': 4,
                  'talents': 1, 'documents': count, 'revision': talent.revision, 'talent_id': talent.id}
        output = Path('/data/verification/concurrency.json')
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
    finally:
        await worker.stores.close()


if __name__ == '__main__':
    asyncio.run(main())
