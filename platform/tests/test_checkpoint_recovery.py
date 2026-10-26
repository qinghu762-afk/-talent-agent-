import asyncio
import json

import httpx
from langgraph.checkpoint.memory import InMemorySaver
import pytest

from talent_platform.ai import AIPlatform


def test_transient_failure_resumes_verified_round_instead_of_resetting_it():
    calls = 0
    async def model(request):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise httpx.ReadTimeout('synthetic transient failure')
        if calls == 1:
            return {'profile': {'name': '合成甲', 'skills': ['Python'], 'evidence': [
                {'field': 'name', 'value': '合成甲', 'quote': '姓名：合成甲'},
                {'field': 'skills', 'value': 'Python', 'quote': '技能：Python'}]}}
        return {'profile': {'email': 'synthetic@example.test', 'education': ['本科'], 'evidence': [
            {'field': 'email', 'value': 'synthetic@example.test', 'quote': '邮箱：synthetic@example.test'},
            {'field': 'education', 'value': '本科', 'quote': '学历：本科'}]}}
    service = AIPlatform(model=model, checkpointer=InMemorySaver())
    async def scenario():
        payload = {'text': '姓名：合成甲\n邮箱：synthetic@example.test\n技能：Python\n学历：本科'}
        kwargs = {'run_id': 'same-durable-task', 'actor': {'id': 'u', 'org_id': 'o', 'role': 'hr'}}
        with pytest.raises(httpx.ReadTimeout):
            await service.execute('resume', payload, **kwargs)
        return await service.execute('resume', payload, **kwargs)
    result = asyncio.run(scenario())
    assert result['report']['quality_status'] == 'complete'
    assert result['report']['retry_count'] == 1 and calls == 3
    summary = result['report']['execution_summary']
    assert len(summary) >= 2
    assert 'synthetic@example.test' not in json.dumps(summary)
    assert 'quote' not in json.dumps(summary)
