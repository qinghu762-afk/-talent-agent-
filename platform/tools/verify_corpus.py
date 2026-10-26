"""Resume-safe real file parsing acceptance on explicitly synthetic fixtures."""
import argparse
import asyncio
import hashlib
import json
import time

from acceptance import Acceptance, ROOT, VERIFY


async def main(cache_batch=False, retry_failed=False, followup=False, confirmation=False):
    fixture_root = VERIFY / 'fixtures'
    manifest = json.loads((fixture_root / 'fixture-manifest.json').read_text('utf-8'))
    assert manifest['synthetic'] and manifest['fixture_count'] >= 30
    fixtures = manifest['fixtures']
    if followup or confirmation:
        failures = json.loads((VERIFY / ('corpus-followup.json' if confirmation else 'corpus.json')).read_text('utf-8'))['files']
        ids = {f['fixture'] for f in failures if not f['passed']}
        fixtures = [f for f in fixtures if f['id'] in ids]
    if cache_batch:
        good = next(f for f in fixtures if f['expected_quality'] == 'complete' and f['type'] == 'txt')
        bad = next(f for f in fixtures if f['scenario'] == 'corrupt')
        fixtures = [good] * 199 + [bad]
    path = VERIFY / ('batch-200.json' if cache_batch else 'corpus-confirmation.json' if confirmation else 'corpus-followup.json' if followup else 'corpus.json')
    report = json.loads(path.read_text('utf-8')) if path.exists() else {'synthetic': True, 'cache_heavy': cache_batch, 'files': []}
    if report.get('retry_batch_id') and not report.get('retry_batches'):
        report['retry_batches'] = [{'id': report['retry_batch_id'], 'fixtures': report['retry_fixtures']}]
    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    client = Acceptance('corpus-confirmation-scope.json' if confirmation else 'corpus-followup-scope.json' if followup else 'runtime-state.json')
    try:
        await client.setup()
        report['org_id'] = client.state['org_id']
        if retry_failed and report.get('run_id'):
            prior = await client.call('hr', 'GET', '/runs/' + report['run_id'])
            effective = {f['id']: entry for entry, f in zip(prior.get('result', {}).get('files', []), fixtures)}
            for batch in report.get('retry_batches', []):
                recent = await client.call('hr', 'GET', '/runs/' + batch['id'])
                effective.update(zip(batch['fixtures'], recent.get('result', {}).get('files', [])))
            retry = []
            for fixture in fixtures:
                entry = effective.get(fixture['id'], {})
                if entry.get('status') == 'failed' and fixture['expected_quality'] != 'fail':
                    retry.append(fixture)
            if retry:
                created = await client.call('hr', 'POST', '/talents/import', 202,
                    files=[('files', (f['filename'], (fixture_root / f['filename']).read_bytes())) for f in retry])
                report['retry_batch_id'] = created['id']
                report['retry_fixtures'] = [f['id'] for f in retry]
                report.setdefault('retry_batches', []).append({'id': created['id'], 'fixtures': report['retry_fixtures']})
                save()
        if not report.get('run_id'):
            upload = []
            for f in fixtures:
                blob = (fixture_root / f['filename']).read_bytes()
                assert hashlib.sha256(blob).hexdigest() == f['sha256']
                upload.append(('files', (f['filename'], blob)))
            created = await client.call('hr', 'POST', '/talents/import', 202, files=upload)
            report.update(run_id=created['id'], started_at=time.time(), count=created['count'])
            save()
        deadline = time.monotonic() + 7200
        prior = None
        while time.monotonic() < deadline:
            run = await client.call('hr', 'GET', '/runs/' + report['run_id'])
            status = (run['status'], run.get('progress'), run.get('result', {}).get('settled'))
            if status != prior:
                print(json.dumps({'batch': report['run_id'], 'status': status}, ensure_ascii=False), flush=True)
                prior = status
                report['last_status'] = status
                save()
            if run['status'] in {'succeeded', 'failed', 'cancelled'}:
                break
            await asyncio.sleep(5)
        else:
            raise TimeoutError('Synthetic corpus batch did not settle in two hours')
        entries = run.get('result', {}).get('files', [])
        assert len(entries) == len(fixtures), 'Batch lost input files'
        overrides = {}
        for batch in report.get('retry_batches', []):
            repaired = await client.wait('hr', batch['id'], timeout=3600)
            overrides.update(zip(batch['fixtures'], repaired['result']['files']))
        observations = []
        profiles = {}
        for entry, fixture in zip(entries, fixtures):
            if cache_batch:
                await asyncio.sleep(1.1)
            original_id = entry['id']
            entry = overrides.get(fixture['id'], entry)
            child = await client.call('hr', 'GET', '/runs/' + entry['id'])
            result = child.get('result', {})
            extraction = result.get('report', {})
            expected = fixture['expected_quality']
            actual = extraction.get('quality_status') if child['status'] == 'succeeded' else 'fail'
            checks = {}
            if result.get('talent_id'):
                if result['talent_id'] not in profiles:
                    profiles[result['talent_id']] = (await client.call('hr', 'GET', '/talents/' + result['talent_id']))['profile']
                profile = profiles[result['talent_id']]
                expected_profile = fixture.get('expected_profile', {})
                checks['name'] = profile.get('name') == expected_profile.get('name')
                if expected_profile.get('email'):
                    checks['email'] = profile.get('email') == expected_profile['email']
                if expected_profile.get('skills'):
                    checks['skills'] = {s.casefold() for s in expected_profile['skills']} <= {s.casefold() for s in profile.get('skills', [])}
                if expected_profile.get('phone') and profile.get('phone'):
                    checks['phone'] = ''.join(c for c in expected_profile['phone'] if c.isdigit()) == ''.join(c for c in profile['phone'] if c.isdigit())
            if expected == 'fail':
                passed = actual == 'fail'
            else:
                passed = actual == expected and all(checks.values())
            observations.append({'fixture': fixture['id'], 'filename': fixture['filename'], 'run_id': child['id'],
                                 'status': child['status'], 'expected': expected, 'actual': actual, 'passed': passed,
                                 'retry_count': extraction.get('retry_count'), 'missing_fields': extraction.get('missing_fields'),
                                 'error': child.get('error'), 'talent_id': result.get('talent_id')})
            observations[-1]['field_checks'] = checks
            if entry['id'] != original_id:
                observations[-1]['original_run_id'] = original_id
        report.update(files=observations, passed=all(f['passed'] for f in observations),
                      seconds=round(time.time() - report['started_at'], 3),
                      matches=sum(f['passed'] for f in observations), completed_at=time.time())
        save()
        print(json.dumps({k: v for k, v in report.items() if k not in {'files'}}, ensure_ascii=False), flush=True)
    finally:
        for session in client.clients.values():
            await session.aclose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache-batch-200', action='store_true')
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--followup', action='store_true')
    parser.add_argument('--confirmation', action='store_true')
    args = parser.parse_args()
    asyncio.run(main(args.cache_batch_200, args.retry_failed, args.followup, args.confirmation))
