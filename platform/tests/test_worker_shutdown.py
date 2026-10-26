import asyncio
import pytest
from test_business import data, login
from test_worker import invoke


def test_worker_cancellation_releases_lease_without_consuming_retry_budget(client):
    from talent_platform.worker import Worker
    from talent_platform.db import Run
    login(client)
    run = data(client.post('/api/v1/talents/text', json={'text': '合成重启简历'}), 202)
    async def interrupted(*args):
        raise asyncio.CancelledError()
    worker = Worker(client.app.state.config, client.app.state.stores, interrupted)
    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await worker.run_once(run['id'])
        async with worker.stores.facts() as db:
            saved = await db.get(Run, run['id'])
            assert saved.status == 'queued' and saved.attempt == 0
        claimed = await worker.claim(run['id'])
        assert claimed and claimed.attempt == 1
    invoke(client, scenario)
