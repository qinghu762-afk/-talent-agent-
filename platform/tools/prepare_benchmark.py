"""Create a distinct synthetic organization through the normal authorized API."""
import asyncio
import json
import secrets
import uuid
from acceptance import Acceptance, VERIFY


async def main():
    path = VERIFY / 'benchmark-scope.json'
    if path.exists():
        print(path.read_text('utf-8'))
        return
    client = Acceptance()
    try:
        await client.login('admin')
        suffix = uuid.uuid4().hex[:10]
        org = await client.call('admin', 'POST', '/organizations', 201,
                                json={'name': '合成万条性能测试 ' + suffix, 'synthetic': True})
        actor = await client.call('admin', 'POST', '/users', 201,
                    json={'username': 'synthetic-benchmark-' + suffix, 'password': secrets.token_urlsafe(40),
                          'role': 'hr', 'org_id': org['id']})
        scope = {'synthetic': True, 'org_id': org['id'], 'actor_id': actor['id']}
        path.write_text(json.dumps(scope, indent=2), encoding='utf-8')
        print(json.dumps(scope))
    finally:
        for session in client.clients.values():
            await session.aclose()


if __name__ == '__main__':
    asyncio.run(main())
