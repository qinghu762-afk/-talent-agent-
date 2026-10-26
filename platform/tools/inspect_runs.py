"""Read-only, privacy-limited summary of new platform task state."""
import asyncio
from collections import Counter
from sqlalchemy import select
from talent_platform.db import Run
from talent_platform.worker import Worker


async def main():
    worker = Worker()
    try:
        async with worker.stores.facts() as db:
            rows = (await db.scalars(select(Run))).all()
            print(dict(Counter((r.kind, r.status) for r in rows)))
            for r in rows:
                if r.status in {'running', 'queued'}:
                    print({'id': r.id, 'kind': r.kind, 'filename': r.payload.get('filename'), 'status': r.status,
                           'lease_until': str(r.lease_until), 'attempt': r.attempt})
    finally:
        await worker.stores.close()


if __name__ == '__main__':
    asyncio.run(main())
