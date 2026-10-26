from test_business import data, login
from test_worker import invoke


def test_dify_can_poll_only_explicitly_registered_skill_and_its_child(client):
    login(client)
    skill = data(client.post('/api/v1/skills', json={'name': '合成岗位解析', 'handler': 'job', 'config': {'allow_dify': True}}), 201)
    headers = {'X-Service-Key': 'test-service-private-key'}
    task = data(client.post('/api/v1/integrations/dify/skills/execute', json={'skill_id': skill['id'], 'parameters': {'description': 'Python'}}, headers=headers), 202)
    endpoint = '/api/v1/integrations/dify/runs/' + task['id']
    assert client.get(endpoint).status_code == 401
    assert data(client.get(endpoint, headers=headers))['status'] == 'queued'
    from talent_platform.worker import Worker
    async def model(*args):
        return {'requirements': {'required_skills': ['Python']}}
    worker = Worker(client.app.state.config, client.app.state.stores, model)
    invoke(client, worker.run_once, task['id'])
    child = data(client.get(endpoint, headers=headers))
    assert child['status'] == 'queued' and child['child_run_id']
    invoke(client, worker.run_once, child['child_run_id'])
    assert data(client.get(endpoint, headers=headers))['result']['job_id']
    data(client.patch('/api/v1/skills/' + skill['id'], json={'enabled': False}))
    assert client.get(endpoint, headers=headers).status_code == 404
