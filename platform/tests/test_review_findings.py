from test_business import data, login
from test_worker import invoke
import json
import pytest


def test_restricted_hr_patch_response_cannot_reveal_stored_contacts(client):
    login(client)
    talent = data(client.post('/api/v1/talents', json={'profile': {'name': '合成', 'phone': '13800138000', 'email': 'synthetic@example.test'}}), 201)
    role = data(client.post('/api/v1/roles', json={'name': '字段受限编辑员', 'base_role': 'hr', 'permissions': ['GET:talents', 'PATCH:talents'], 'denied_fields': ['phone', 'email']}), 201)
    data(client.post('/api/v1/users', json={'username': 'restricted', 'password': 'Employee123!', 'role_template_id': role['id']}), 201)
    client.post('/api/v1/auth/logout')
    login(client, 'restricted', 'Employee123!')
    response = client.patch('/api/v1/talents/' + talent['id'], json={'tags': []})
    assert response.status_code == 200
    assert '13800138000' not in response.text and 'synthetic@example.test' not in response.text


@pytest.mark.parametrize('content_type', ['application/json', 'application/vnd.api+json', 'Application/JSON', None])
def test_restricted_profile_editor_cannot_overwrite_or_drop_hidden_contacts(client, content_type):
    login(client)
    talent = data(client.post('/api/v1/talents', json={'profile': {'name': '合成', 'email': 'synthetic@example.test'}}), 201)
    role = data(client.post('/api/v1/roles', json={'name': '受限编辑', 'base_role': 'hr', 'permissions': ['GET:talents', 'PATCH:talents'], 'denied_fields': ['email']}), 201)
    data(client.post('/api/v1/users', json={'username': 'hiddeneditor', 'password': 'Employee123!', 'role_template_id': role['id']}), 201)
    client.post('/api/v1/auth/logout')
    login(client, 'hiddeneditor', 'Employee123!')
    headers = {'Content-Type': content_type} if content_type else {}
    assert client.patch('/api/v1/talents/' + talent['id'], content=json.dumps({'profile': {'email': 'changed@example.test'}}), headers=headers).status_code == 403
    data(client.patch('/api/v1/talents/' + talent['id'], json={'profile': {'name': '新合成'}}))
    client.post('/api/v1/auth/logout')
    login(client)
    profile = data(client.get('/api/v1/talents/' + talent['id']))['profile']
    assert profile['name'] == '新合成' and profile['email'] == 'synthetic@example.test'


def test_global_admin_analysis_is_not_shared_with_home_org_manager(client):
    login(client)
    who = data(client.get('/api/v1/auth/me'))
    data(client.post('/api/v1/users', json={'username': 'manager', 'password': 'Employee123!', 'role': 'manager'}), 201)
    from talent_platform.db import Record, Run
    async def seed():
        async with client.app.state.stores.facts() as db:
            run = Run(kind='analysis', status='succeeded', org_id=who['org_id'], owner_id=who['id'], actor=who, result={'rows': [['foreign-secret']], 'columns': ['name']})
            db.add(run)
            await db.flush()
            report = Record(kind='reports', org_id=who['org_id'], owner_id=who['id'], data={'run_id': run.id, 'columns': ['name'], 'rows': [['foreign-secret']]})
            db.add(report)
            await db.commit()
            return run.id, report.id
    run_id, report_id = invoke(client, seed)
    client.post('/api/v1/auth/logout')
    login(client, 'manager', 'Employee123!')
    assert client.get('/api/v1/runs/' + run_id).status_code == 404
    assert client.get('/api/v1/reports/' + report_id).status_code == 404
    assert client.get('/api/v1/reports/' + report_id + '/export').status_code == 404
    assert 'foreign-secret' not in client.get('/api/v1/runs').text
    assert 'foreign-secret' not in client.get('/api/v1/reports').text


def test_manager_cannot_use_resume_skill_as_privileged_workflow(client):
    login(client)
    skill = data(client.post('/api/v1/skills', json={'name': '简历解析', 'handler': 'resume', 'enabled': True}), 201)
    data(client.post('/api/v1/users', json={'username': 'manager', 'password': 'Employee123!', 'role': 'manager'}), 201)
    client.post('/api/v1/auth/logout')
    who = login(client, 'manager', 'Employee123!')
    assert client.post('/api/v1/skills/' + skill['id'] + '/execute', json={'parameters': {'text': '合成简历'}}).status_code == 403
    from talent_platform.tasks import enqueue
    from talent_platform.worker import Worker
    async def seed():
        return await enqueue(client.app.state.stores, who, 'resume', {'sha256': 'x', 'text': '合成'})
    run = invoke(client, seed)
    async def forbidden(*args):
        raise AssertionError('base role bypass reached model')
    worker = Worker(client.app.state.config, client.app.state.stores, forbidden)
    invoke(client, worker.run_once, run.id)
    assert data(client.get('/api/v1/runs/' + run.id))['status'] == 'failed'


def test_cancel_during_job_model_call_does_not_commit_job(client):
    login(client)
    run = data(client.post('/api/v1/jobs/import', files={'file': ('synthetic.txt', b'Python developer')}), 202)
    from talent_platform.db import Run
    from talent_platform.worker import Worker
    async def cancel_then_return(kind, payload, run_id, actor):
        async with client.app.state.stores.facts() as db:
            row = await db.get(Run, run_id)
            row.status = 'cancelled'
            await db.commit()
        return {'requirements': {'required_skills': ['Python']}}
    worker = Worker(client.app.state.config, client.app.state.stores, cancel_then_return)
    invoke(client, worker.run_once, run['id'])
    assert data(client.get('/api/v1/runs/' + run['id']))['status'] == 'cancelled'
    assert data(client.get('/api/v1/jobs'))['total'] == 0


def test_cancel_during_knowledge_parser_does_not_commit_document(client):
    login(client)
    who = data(client.get('/api/v1/auth/me'))
    from talent_platform.db import Run
    from talent_platform.tasks import enqueue
    from talent_platform.worker import Worker
    async def seed():
        return await enqueue(client.app.state.stores, who, 'knowledge_import', {'path': 'synthetic', 'filename': 'synthetic.pdf', 'title': '合成资料', 'scope': 'org'})
    run = invoke(client, seed)
    async def parse_then_cancel(*args):
        async with client.app.state.stores.facts() as db:
            row = await db.get(Run, run.id)
            row.status = 'cancelled'
            await db.commit()
        return '合成知识正文'
    worker = Worker(client.app.state.config, client.app.state.stores)
    worker.parse = parse_then_cancel
    invoke(client, worker.run_once, run.id)
    assert data(client.get('/api/v1/knowledge'))['total'] == 0


def test_merge_undo_returns_new_contact_identity_to_restored_profile(client):
    login(client)
    who = data(client.get('/api/v1/auth/me'))
    from talent_platform.persistence import persist_resume, undo_merge
    stores = client.app.state.stores
    first = invoke(client, persist_resume, stores, who, {'sha256': 'a' * 64, 'filename': 'a.txt', 'path': 'a'}, {'profile': {'name': '合成甲', 'phone': '13800138000'}})
    second = invoke(client, persist_resume, stores, who, {'sha256': 'b' * 64, 'filename': 'b.txt', 'path': 'b'}, {'profile': {'name': '合成甲', 'phone': '13800138000', 'email': 'synthetic@example.test'}})
    assert second['talent_id'] == first['talent_id']
    undone = invoke(client, undo_merge, stores, who, second['merge_id'])
    third = invoke(client, persist_resume, stores, who, {'sha256': 'c' * 64, 'filename': 'c.txt', 'path': 'c'}, {'profile': {'name': '合成甲', 'email': 'synthetic@example.test'}})
    assert third['talent_id'] == undone['restored_talent_id']
