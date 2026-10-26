"""Replay a synthetic failed analysis through the real model; never print credentials."""
import asyncio
import sys
from talent_platform.worker import Worker
from talent_platform.db import Run, Resource
from talent_platform.analysis import AnalyticsEngine
from talent_platform.ai import DifyGateway

async def main():
    worker = Worker()
    async with worker.stores.facts() as db:
        run = await db.get(Run, sys.argv[1])
    async with worker.stores.business() as db:
        org = await db.get(Resource, run.org_id)
        assert org and org.data.get('synthetic'), 'Synthetic organization required'
    gateway = DifyGateway()
    async def traced(request, actor):
        answer = await gateway({**request, 'user': actor['id']})
        print({'task': request['task'], 'output': answer}, flush=True)
        return answer
    try:
        engine = AnalyticsEngine(model=traced)
        await engine.execute(run.payload['__snapshot'], actor=await worker.current_actor(run))
    finally:
        await worker.stores.close()

if __name__ == '__main__':
    asyncio.run(main())
