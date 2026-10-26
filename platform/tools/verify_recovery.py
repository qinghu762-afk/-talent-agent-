"""HTTP stages around an operator-controlled restart of only the new worker."""
import argparse
import asyncio
import json
import time
import uuid
from acceptance import Acceptance, COMPLETE, VERIFY


async def main(stage, active=False):
    path = VERIFY / ('recovery-active.json' if active else 'recovery.json')
    state = json.loads(path.read_text('utf-8')) if path.exists() else {'synthetic': True, 'suffix': uuid.uuid4().hex[:12]}
    client = Acceptance()
    def save():
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        await client.setup()
        if stage == 'before':
            if not state.get('run_id'):
                text = COMPLETE.replace('张合成', '合成恢复' + state['suffix']).replace('电话：13800138000', '邮箱：recovery-' + state['suffix'] + '@example.test')
                if active:
                    text = ('合成服务重启长文档验收\n' + text + '\n') * 40
                task = await client.call('hr', 'POST', '/talents/text', 202, json={'text': text})
                state['run_id'] = task['id']
                save()
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                run = await client.call('hr', 'GET', '/runs/' + state['run_id'])
                if run['status'] == 'running':
                    state['before'] = {'status': run['status'], 'attempt': run['attempt']}
                    save()
                    print(json.dumps({'ready_for_new_worker_restart': True, 'run_id': state['run_id']}), flush=True)
                    return
                assert run['status'] not in {'failed', 'succeeded', 'cancelled'}, 'Restart test needs an active task'
                await asyncio.sleep(.5)
            raise TimeoutError('Task did not start')
        run = await client.wait('hr', state['run_id'])
        assert run['status'] == 'succeeded' and run['result'].get('document_id')
        ident = run['result']['talent_id']
        talent = await client.call('hr', 'GET', '/talents/' + ident)
        assert sum(d['id'] == run['result']['document_id'] for d in talent['documents']) == 1
        endpoint = '/runs/' + state['run_id'] + '/events'
        response = await client.call('hr', 'GET', endpoint)
        ids = [int(line[4:]) for line in response.text.splitlines() if line.startswith('id: ')]
        statuses = [json.loads(line[6:])['status'] for line in response.text.splitlines() if line.startswith('data: ')]
        assert len(ids) >= 3 and len(ids) == len(set(ids)) and ids == sorted(ids)
        cut = ids[len(ids) // 2]
        reconnect = await client.call('hr', 'GET', endpoint, headers={'Last-Event-ID': str(cut)})
        resumed = [int(line[4:]) for line in reconnect.text.splitlines() if line.startswith('id: ')]
        assert resumed == [seq for seq in ids if seq > cut]
        cancel = await client.call('hr', 'POST', '/talents/text', 202, json={'text': '合成取消测试 ' + state['suffix']})
        await client.call('hr', 'POST', '/runs/' + cancel['id'] + '/cancel')
        cancelled = await client.call('hr', 'GET', '/runs/' + cancel['id'])
        assert cancelled['status'] == 'cancelled' and not cancelled['result']
        restart_observed = any(statuses[i:i+3] == ['running', 'queued', 'running'] for i in range(len(statuses)-2))
        state.update(passed=restart_observed if active else True, after={'status': run['status'], 'attempt': run['attempt'], 'talent_id': ident,
                     'document_id': run['result']['document_id'], 'sse_events': len(ids), 'resumed_after': cut,
                     'cancelled_run': cancel['id'], 'single_original_document': True,
                     'status_sequence': statuses, 'active_lease_recovery_observed': restart_observed})
        save()
        print(json.dumps(state), flush=True)
        if active:
            assert restart_observed, 'No active lease interruption was observed; a completed-before-restart run is insufficient'
    finally:
        for session in client.clients.values():
            await session.aclose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['before', 'after'], required=True)
    parser.add_argument('--active', action='store_true')
    args = parser.parse_args()
    asyncio.run(main(args.stage, args.active))
