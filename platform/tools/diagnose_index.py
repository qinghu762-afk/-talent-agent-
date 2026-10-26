"""Read only version metadata for a synthetic index task."""
import asyncio
import json
import sys
from talent_platform.worker import Worker
from talent_platform.db import Run, Record, Resource

async def main():
    worker = Worker()
    try:
        async with worker.stores.facts() as db:
            run = await db.get(Run, sys.argv[1])
            row = await db.get(Record, run.payload['talent_id'])
        async with worker.stores.business() as db:
            org = await db.get(Resource, run.org_id)
            assert org.data.get('synthetic')
        print(json.dumps({'run': run.id, 'status': run.status, 'attempt': run.attempt, 'result': run.result,
            'revision': row.revision, 'indexed_revision': row.indexed_revision,
            'snapshot_revision': run.payload.get('__snapshot', {}).get('talent', {}).get('revision'),
            'index_model': row.data.get('index_model')}, ensure_ascii=False))
    finally:
        await worker.stores.close()

if __name__ == '__main__':
    asyncio.run(main())
