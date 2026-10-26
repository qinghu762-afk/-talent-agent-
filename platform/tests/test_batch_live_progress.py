from test_business import data, login
from test_worker import invoke


def test_batch_reports_live_child_progress_between_parent_claims(client):
    login(client)
    run = data(client.post('/api/v1/talents/import', files=[('files', ('one.txt', b'one')), ('files', ('two.txt', b'two'))]), 202)
    from talent_platform.worker import Worker
    from talent_platform.db import Run
    worker = Worker(client.app.state.config, client.app.state.stores)
    invoke(client, worker.run_once, run['id'])
    initial = data(client.get('/api/v1/runs/' + run['id']))
    child_id = initial['result']['files'][0]['id']
    async def finish_child():
        async with client.app.state.stores.facts() as db:
            child = await db.get(Run, child_id)
            child.status = 'failed'
            child.error = 'synthetic corrupt file'
            await db.commit()
    invoke(client, finish_child)
    current = data(client.get('/api/v1/runs/' + run['id']))
    assert current['result']['files'][0]['status'] == 'failed'
    assert current['result']['settled'] == 1 and current['progress'] == 50
