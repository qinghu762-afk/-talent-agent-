import pytest
from test_ai import Responses, platform, run


def talent(key='t', org='o', revision=2):
    return {'id': key, 'org_id': org, 'revision': revision, 'indexed_revision': revision, 'index_model': 'e',
            'profile': {'source': 'manual', 'verified_by': 'hr', 'name': key, 'skills': ['Python']}}


def test_search_uses_authorized_current_vector_snapshots():
    class Vectors:
        async def search(self, query, **scope):
            assert scope['allowed_ids'] == ['t']
            return [{'source_id': 't', 'org_id': 'o', 'kind': 'talent', 'revision': 2, 'index_model': 'e', 'text': 'Python', 'chunk': 0, 'semantic_score': .9},
                    {'source_id': 't', 'org_id': 'o', 'revision': 1, 'index_model': 'e', 'text': 'old', 'chunk': 1},
                    {'source_id': 'secret', 'org_id': 'o', 'revision': 2, 'index_model': 'e', 'text': 'secret', 'chunk': 0}]
    result = run(platform(Responses({}), Vectors()), 'search', {'query': 'Python', 'talents': [talent(), talent('secret')], 'allowed_ids': ['t']})
    assert [item['talent_id'] for item in result['items']] == ['t']
    assert result['items'][0]['evidence'][0]['text'] == 'Python'
    assert len(result['items'][0]['evidence']) == 1


def test_match_admin_uses_job_organization_and_ignores_other_org_snapshot():
    import asyncio
    calls = []
    class Vectors:
        async def search(self, query, **scope):
            calls.append(scope)
            return [{'source_id': 't', 'org_id': 'target', 'revision': 2, 'index_model': 'e', 'text': 'Python', 'chunk': 0}]
    result = asyncio.run(platform(Responses({}), Vectors()).execute('match', {
        'job': {'org_id': 'target', 'requirements': {'required_skills': ['Python']}},
        'talents': [talent(org='target'), talent('other')], 'allowed_ids': ['t', 'other']},
        run_id='admin', actor={'id': 'a', 'org_id': 'o', 'role': 'admin'}))
    assert calls[0]['org_id'] == 'target'
    assert calls[0]['allowed_ids'] == ['t']
    assert result['candidates'][0]['talent_id'] == 't'


def test_nonadmin_cannot_match_foreign_organization_job():
    with pytest.raises(ValueError, match='organization'):
        run(platform(Responses({})), 'match', {'job': {'org_id': 'foreign'}, 'talents': [], 'allowed_ids': []})


def test_chat_mixed_kinds_retrieves_grouped_and_rejects_stale_semantic_boost():
    calls = []
    class Vectors:
        async def search(self, query, **scope):
            calls.append(scope)
            if scope['kind'] == 'talent':
                return [{'source_id': 't', 'org_id': 'o', 'kind': 'talent', 'revision': 1, 'index_model': 'e', 'text': 'Python', 'chunk': 0, 'semantic_score': 1}]
            return []
    model = Responses({'order': [0, 1]}, {'answer': '两份资料都有Python', 'citations': [{'source_id': 't', 'quote': 'Python'}, {'source_id': 'k', 'quote': 'Python'}]})
    result = run(platform(model, Vectors()), 'chat', {'question': 'Python', 'documents': [
        {'id': 't', 'org_id': 'o', 'kind': 'talent', 'revision': 2, 'indexed_revision': 2, 'index_model': 'e', 'text': 'Python人才', 'title': '人才'},
        {'id': 'k', 'org_id': 'o', 'kind': 'knowledge', 'revision': 1, 'indexed_revision': 1, 'index_model': 'e', 'text': 'Python政策', 'title': '知识'}]})
    assert {scope['kind'] for scope in calls} == {'talent', 'knowledge'}
    assert [item['hybrid_score'] for item in model.calls[0]['candidates']] == [.45, .45]
    assert len(result['citations']) == 2
    assert result['citations'][0]['revision'] == 2


def test_semantic_hit_text_must_match_current_document_chunk():
    class Vectors:
        async def search(self, query, **scope):
            return [{'source_id': 'k', 'revision': 2, 'index_model': 'e', 'text': 'stale secret', 'chunk': 0, 'semantic_score': 1}]
    model = Responses({'order': [0]}, {'answer': 'secret', 'citations': [{'source_id': 'k', 'quote': 'secret'}]})
    result = run(platform(model, Vectors()), 'chat', {'question': 'secret', 'documents': [
        {'id': 'k', 'org_id': 'o', 'revision': 2, 'indexed_revision': 2, 'index_model': 'e', 'text': 'current policy'}]})
    assert result['citations'] == []
    assert model.calls == []


@pytest.mark.parametrize('field,value,text', [
    ('required_skills', ['Python'], '不要求Python'),
    ('required_certificates', ['PMP'], '无需PMP'),
    ('min_education', '本科', '不限制本科'),
])
def test_job_negated_constraints_cannot_become_hard_filters(field, value, text):
    scalar = value[0] if isinstance(value, list) else value
    model = Responses({'requirements': {field: value, 'evidence': [{'field': field, 'value': scalar, 'quote': text}]}})
    with pytest.raises(ValueError, match='evidence'):
        run(platform(model), 'job', {'description': text})
