from test_business import data, login
from test_worker import invoke


def test_worker_hash_reuse_preserves_original_extraction_report(client):
    login(client)
    who = data(client.get('/api/v1/auth/me'))
    from talent_platform.persistence import persist_resume
    from talent_platform.uploads import save_file
    from talent_platform.worker import Worker
    from talent_platform.tasks import enqueue
    digest, path = save_file(client.app.state.config.data_dir, 'synthetic.txt', b'synthetic')
    source = {'sha256': digest, 'path': path, 'filename': 'synthetic.txt'}
    report = {'quality_status': 'partial', 'missing_fields': ['contact'], 'retry_count': 1, 'versions': {'prompt_sha256': 'original-version'}}
    first = invoke(client, persist_resume, client.app.state.stores, who, source, {'profile': {'name': '合成甲'}, 'report': report})
    async def seed():
        return await enqueue(client.app.state.stores, who, 'resume', source)
    task = invoke(client, seed)
    async def never(*args):
        raise AssertionError('cached document must never call model')
    worker = Worker(client.app.state.config, client.app.state.stores, never)
    invoke(client, worker.run_once, task.id)
    result = data(client.get('/api/v1/runs/' + task.id))
    assert result['result']['talent_id'] == first['talent_id']
    assert result['result']['report'] == report
    assert result['versions']['prompt_sha256'] == 'original-version'
