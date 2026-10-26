"""Real role/field/row authorization checks using synthetic records only."""
import asyncio
import json
import uuid
from acceptance import Acceptance, VERIFY


async def main():
    client = Acceptance()
    try:
        await client.setup()
        await client.login('tooladmin')
        await client.login('employee')
        suffix = uuid.uuid4().hex[:8]
        private_email = 'permission-' + suffix + '@example.test'
        talent = await client.call('tooladmin', 'POST', '/talents', 201,
                    json={'profile': {'name': '合成字段权限' + suffix, 'email': private_email}})
        role = await client.call('tooladmin', 'POST', '/roles', 201, json={
            'name': '合成受限编辑' + suffix, 'base_role': 'hr', 'permissions': ['GET:talents', 'PATCH:talents'],
            'denied_fields': ['phone', 'email'], 'data_scope': 'org'})
        username = 'synthetic-' + client.state['id'] + '-restricted'
        user = await client.call('tooladmin', 'POST', '/users', 201, json={
            'username': username + '-' + suffix, 'password': client.password('restricted'),
            'role_template_id': role['id'], 'org_id': client.state['org_id']})
        import httpx
        client.clients['restricted'] = httpx.AsyncClient(base_url='http://127.0.0.1:18080', timeout=30,
                                                       trust_env=False, headers={'Origin': 'http://127.0.0.1:18080'})
        await client.call('restricted', 'POST', '/auth/login', json={'username': username + '-' + suffix,
                                                                   'password': client.password('restricted')})
        uri = '/talents/' + talent['id']
        restricted = await client.call('restricted', 'GET', uri)
        assert private_email not in json.dumps(restricted)
        await client.call('restricted', 'PATCH', uri, 403, json={'profile': {'email': 'forbidden@example.test'}})
        for mime in ('application/vnd.api+json', 'Application/JSON'):
            await client.call('restricted', 'PATCH', uri, 403,
                content=json.dumps({'profile': {'email': 'forbidden@example.test'}}), headers={'Content-Type': mime})
        patched = await client.call('restricted', 'PATCH', uri, json={'profile': {'name': '合成可见字段编辑'}})
        assert private_email not in json.dumps(patched)
        assert (await client.call('tooladmin', 'GET', uri))['profile']['email'] == private_email
        await client.call('restricted', 'POST', '/talents/text', 403, json={'text': '合成未授权解析'})
        await client.call('restricted', 'GET', '/jobs', 403)
        manager = await client.call('manager', 'GET', '/talents/' + client.state['talent_id'])
        assert '13800138000' not in json.dumps(manager) and '"phone"' not in json.dumps(manager)
        foreign = await client.clients['employee'].get('/api/v1/talents/' + talent['id'])
        assert foreign.status_code in {403, 404}
        document = client.state['document_id']
        await client.call('manager', 'GET', '/documents/' + document + '/file', 403)
        await client.call('tooladmin', 'PATCH', '/users/' + user['id'], json={'active': False})
        await client.call('restricted', 'GET', uri, 401)
        report = {'passed': True, 'synthetic': True, 'org_id': client.state['org_id'],
                  'checks': ['field_read_redaction', 'hidden_field_write_denied', 'json_mime_variants_denied', 'patch_preserves_hidden_fields',
                             'operation_scope', 'employee_row_scope', 'manager_contact_redaction',
                             'original_file_denied', 'disabled_user_session_rejected']}
        (VERIFY / 'permissions.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
    finally:
        for session in client.clients.values():
            await session.aclose()


if __name__ == '__main__':
    asyncio.run(main())
