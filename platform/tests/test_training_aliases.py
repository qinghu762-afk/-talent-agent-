import asyncio
from langgraph.checkpoint.memory import InMemorySaver
from talent_platform.ai import AIPlatform


def test_training_restores_authorized_course_aliases_and_freezes_model_version(monkeypatch):
    monkeypatch.setenv('CHAT_MODEL', 'original-local-model')
    async def model(request):
        assert request['courses'][0]['id'] == 'C1'
        return {'title': 'Python能力提升', 'course_ids': ['C1'], 'reasons': {'C1': 'Python测评未通过'}}
    service = AIPlatform(model=model, checkpointer=InMemorySaver())
    payload = {'talent': {'profile': {'skills': ['Python']}}, 'assessment': {'dimensions': {'Python': 0}},
               'courses': [{'id': 'exact-authorized-course-id', 'title': 'Python基础', 'skills': ['Python']}]}
    async def scenario():
        kwargs = {'run_id': 'same-training', 'actor': {'id': 'u', 'org_id': 'o', 'role': 'hr'}}
        first = await service.execute('training', payload, **kwargs)
        monkeypatch.setenv('CHAT_MODEL', 'new-local-model')
        again = await service.execute('training', payload, **kwargs)
        assert again['versions']['chat_model'] == 'original-local-model'
        return first
    result = asyncio.run(scenario())
    assert result['course_ids'] == ['exact-authorized-course-id']
    assert result['reasons'] == {'exact-authorized-course-id': 'Python测评未通过'}
