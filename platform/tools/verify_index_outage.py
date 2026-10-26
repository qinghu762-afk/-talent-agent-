"""HTTP stages around a brief outage of only the new Milvus service."""
import argparse
import asyncio
import json
import time
import uuid
from acceptance import Acceptance, VERIFY


async def main(stage):
    path = VERIFY / 'index-outage.json'
    report = json.loads(path.read_text('utf-8')) if path.exists() else {'synthetic': True}
    def save():
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    client = Acceptance()
    try:
        await client.setup()
        if stage == 'before':
            previous = {run['id'] for run in (await client.call('hr', 'GET', '/runs'))['items']}
            talent = await client.call('hr', 'POST', '/talents', 201, json={
                'profile': {'name': '合成索引故障' + uuid.uuid4().hex[:8], 'skills': ['Python'],
                            'education': [{'degree': '本科'}]}})
            runs = (await client.call('hr', 'GET', '/runs'))['items']
            pending = [run for run in runs if run['id'] not in previous and run['kind'] == 'index']
            assert len(pending) == 1, 'Expected exactly one new synthetic index outbox record'
            report.update(talent_id=talent['id'], run_id=pending[0]['id'])
            save()
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                run = await client.call('hr', 'GET', '/runs/' + report['run_id'])
                assert run['status'] != 'succeeded', 'Outage was not observed'
                if run['attempt'] >= 1 and run['status'] in {'queued', 'failed'}:
                    assert run['status'] == 'queued', 'Temporary outage must remain retryable'
                    talent = await client.call('hr', 'GET', '/talents/' + report['talent_id'])
                    assert talent['indexed_revision'] != talent['revision']
                    report['before'] = {'status': run['status'], 'attempt': run['attempt'], 'excluded_until_indexed': True}
                    save()
                    print(json.dumps(report), flush=True)
                    return
                await asyncio.sleep(1)
            raise TimeoutError('Index did not record a bounded temporary failure')
        run = await client.wait('hr', report['run_id'])
        talent = await client.call('hr', 'GET', '/talents/' + report['talent_id'])
        assert run['status'] == 'succeeded' and run['attempt'] >= 2
        assert talent['revision'] == talent['indexed_revision']
        report.update(passed=True, after={'status': run['status'], 'attempt': run['attempt'],
                                         'revision': talent['revision'], 'indexed_revision': talent['indexed_revision']})
        save()
        print(json.dumps(report), flush=True)
    finally:
        for session in client.clients.values():
            await session.aclose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['before', 'after'], required=True)
    asyncio.run(main(parser.parse_args().stage))
