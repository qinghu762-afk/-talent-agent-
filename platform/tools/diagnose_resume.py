"""Trace validation of explicitly synthetic corpus inputs without modifying facts."""
import asyncio
import json
import sys
import uuid
from talent_platform.ai import AIPlatform, DifyGateway, Extraction
from talent_platform.ai_domain import ground_profile, fact_count
from talent_platform.db import Run, Resource
from talent_platform.worker import Worker


async def main():
    worker = Worker()
    try:
        async with worker.stores.facts() as db:
            run = await db.get(Run, sys.argv[1])
        async with worker.stores.business() as db:
            org = await db.get(Resource, run.org_id)
            assert org.data.get('synthetic')
        source = run.payload.get('__snapshot', {}).get('text') or await worker.parse(run.payload['path'], run.payload['filename'])
        gateway = DifyGateway()
        async def traced(request):
            output = await gateway(request)
            try:
                profile, issues = ground_profile(Extraction.model_validate(output).profile, source)
                print(json.dumps({'keys': list(output), 'facts': fact_count(profile), 'issues': issues,
                                  'profile_keys': list(output.get('profile', {})), 'output': output}, ensure_ascii=False), flush=True)
            except ValueError as exc:
                print({'format_error': str(exc), 'output': output}, flush=True)
            return output
        result = await AIPlatform(model=traced).execute('resume', {'text': source}, run_id='diagnostic-' + str(uuid.uuid4()), actor=await worker.current_actor(run))
        print(result['report'])
    finally:
        await worker.stores.close()


if __name__ == '__main__':
    asyncio.run(main())
