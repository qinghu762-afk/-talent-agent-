"""Invoke the registered API tool through independent Dify, with no secret output."""
import asyncio
import json
import sys
import time
from acceptance import Acceptance, ROOT, VERIFY, COMPLETE

sys.path.insert(0, str(ROOT / 'infra'))
from bootstrap_dify import Bootstrap, skills_schema


def business_response(value):
    if isinstance(value, str):
        try:
            return business_response(json.loads(value))
        except ValueError:
            return None
    if isinstance(value, dict):
        if value.get('code') == 'ok' and isinstance(value.get('data'), dict):
            return value['data']
        for item in value.values():
            result = business_response(item)
            if result:
                return result
    if isinstance(value, list):
        for item in value:
            result = business_response(item)
            if result:
                return result
    return None


async def main():
    client = Acceptance()
    bootstrap = Bootstrap('http://127.0.0.1:18081', ROOT / '.env')
    try:
        await client.setup()
        await asyncio.to_thread(bootstrap.setup)
        if not client.state.get('tooladmin_id'):
            user = await client.call('admin', 'POST', '/users', 201, json={
                'username': 'synthetic-' + client.state['id'] + '-tooladmin', 'password': client.password('tooladmin'),
                'role': 'admin', 'org_id': client.state['org_id']})
            client.state['tooladmin_id'] = user['id']
            client.save()
        await client.login('tooladmin')
        skill = await client.call('tooladmin', 'POST', '/skills', 201, json={
            'name': '合成 Dify 工具验收', 'handler': 'resume', 'version': 'synthetic-1',
            'enabled': True, 'config': {'allow_dify': True},
            'input_schema': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}})
        credentials = {'auth_type': 'api_key_header', 'api_key_header': 'X-Service-Key',
                       'api_key_value': bootstrap.values['INTERNAL_SERVICE_KEY'], 'api_key_header_prefix': 'custom'}
        async def invoke(name, parameters):
            result = await asyncio.to_thread(bootstrap.call, 'POST', '/workspaces/current/tool-provider/api/test/pre',
                json={'tool_name': name, 'provider_name': '人才平台授权技能', 'credentials': credentials,
                      'parameters': parameters, 'schema_type': 'openapi', 'schema': json.dumps(skills_schema(), ensure_ascii=False)})
            parsed = business_response(result)
            if parsed is None:
                print({'preview_keys': list(result), 'tool': name}, flush=True)
                raise AssertionError('Dify preview did not return a platform business response')
            return parsed
        created = await invoke('executeTalentSkill', {'skill_id': skill['id'], 'org_id': client.state['org_id'],
                                                     'parameters': {'text': COMPLETE}})
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            result = await invoke('getTalentSkillResult', {'run_id': created['id']})
            if result['status'] == 'succeeded':
                assert result.get('result', {}).get('talent_id') == client.state['talent_id'], 'Dify must observe the real child business result'
                report = {'passed': True, 'synthetic': True, 'skill_id': skill['id'], 'run_id': created['id'],
                          'child_run_id': result['child_run_id'], 'talent_id': result['result']['talent_id'],
                          'cached_business_input': True,
                          'path': 'Dify API tool executor -> authenticated platform API -> durable child -> Dify result tool'}
                (VERIFY / 'dify-tools.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                print(json.dumps(report), flush=True)
                return
            assert result['status'] not in {'failed', 'cancelled'}, {key: result.get(key) for key in ('status', 'error', 'child_run_id')}
            await asyncio.sleep(3)
        raise TimeoutError('Dify child did not settle')
    finally:
        bootstrap.client.close()
        for session in client.clients.values():
            await session.aclose()


if __name__ == '__main__':
    asyncio.run(main())
