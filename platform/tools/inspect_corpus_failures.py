"""Inspect only selected, explicitly synthetic corpus task snapshots."""
import asyncio
import json
import sys
from talent_platform.db import Run, Document, Resource
from talent_platform.worker import Worker

async def main():
    worker = Worker()
    try:
        for ident in sys.argv[1:]:
            async with worker.stores.facts() as db:
                run = await db.get(Run, ident)
                doc = await db.get(Document, run.result.get('document_id')) if run.result.get('document_id') else None
            async with worker.stores.business() as db:
                org = await db.get(Resource, run.org_id)
                assert org.data.get('synthetic')
            snapshot = run.payload.get('__snapshot', {})
            print(json.dumps({'id': ident, 'filename': run.payload.get('filename'), 'source': snapshot.get('text'),
                              'extraction': doc.extracted if doc else None}, ensure_ascii=False), flush=True)
    finally:
        await worker.stores.close()

if __name__ == '__main__':
    asyncio.run(main())
