import asyncio

import pytest
from test_ai import Responses, platform
from test_ai_resume_quality import facts


def execute(service, kind, payload, *, role='admin'):
    return asyncio.run(service.execute(kind, payload, run_id='extra', actor={'id': 'a', 'org_id': 'o', 'role': role}))


def test_summary_tags_only_describe_verified_facts_and_preserve_normalization_sources():
    from talent_platform.ai_domain import ground_profile, verified_values
    raw = facts(name='张三', phone='+86 138 0013 8000', skills=['python'], education=[{'degree': '大学本科'}],
                experiences=[{'company': '甲公司', 'role': '工程师', 'start': '2020年1月', 'end': '2024/01'}],
                projects=[{'name': '采购系统'}])['profile']
    source = '张三\n+86 138 0013 8000\npython\n大学本科\n甲公司 工程师 2020年1月 2024/01\n采购系统'
    profile, _ = ground_profile(raw, source)
    assert profile['phone'] == '13800138000'
    assert profile['education'] == [{'degree': '本科'}]
    assert profile['experiences'][0]['start'] == '2020-01'
    assert profile['experiences'][0]['end'] == '2024-01'
    assert verified_values(profile, 'education') == [{'degree': '本科'}]
    assert profile['tags'] == ['Python']
    assert '甲公司' in profile['summary'] and '工程师' in profile['summary'] and '采购系统' in profile['summary']
    assert '本科' in profile['summary']
    assert profile['derived_fields']['summary']['inference'] is False
    evidence = next(e for e in profile['evidence'] if e['field'] == 'education')
    assert evidence['value'] == {'degree': '大学本科'}
    assert evidence['normalized_value'] == {'degree': '本科'}
    assert evidence['quote'] == '大学本科'


def test_summary_does_not_copy_unverified_model_claims():
    from talent_platform.ai_domain import ground_profile
    profile, _ = ground_profile({'skills': ['Python'], 'summary': '优秀领导者', 'tags': ['高潜'], 'evidence': []}, 'Python')
    assert profile['summary'] == '' and profile['tags'] == []


def test_education_synonyms_do_not_fail_verified_manual_job_matching():
    from talent_platform.ai_domain import score_candidate
    score = score_candidate({'min_education': '学士'}, {'source': 'manual', 'verified_by': 'hr',
                           'education': [{'degree': '大学本科'}]}, [{'text': '大学本科'}])
    assert score['eligible'] is False
    assert next(item for item in score['conditions'] if item['name'] == 'education')['status'] == 'pass'


@pytest.mark.parametrize('kind', ['index', 'duplicates', 'knowledge', 'delete_index'])
def test_admin_uses_authorized_target_org_for_index_operations(kind):
    scopes = []
    class Vectors:
        async def upsert(self, document, **scope):
            scopes.append(document['org_id'])
            return {'indexed_revision': 1}
        async def search(self, query, **scope):
            scopes.append(scope['org_id'])
            return []
        async def delete(self, **scope):
            scopes.append(scope['org_id'])
            return {'deleted': True}
    document = {'id': 't', 'org_id': 'target', 'revision': 1, 'profile': {}, 'text': 'Python'}
    payload = {'talent': document, 'document': document, 'id': 't', 'kind': 'talent', 'org_id': 'target', 'allowed_ids': ['other']}
    execute(platform(Responses({}), Vectors()), kind, payload)
    assert scopes == ['target']
    with pytest.raises(ValueError, match='[Uu]nauthorized'):
        execute(platform(Responses({}), Vectors()), kind, payload, role='hr')


def test_talent_recall_groups_by_source_while_knowledge_recall_keeps_chunks(monkeypatch):
    from talent_platform.ai import MilvusIndex
    class Client:
        def search(self, collection, **kwargs):
            if 'kind == "talent"' in kwargs['filter']:
                assert kwargs['group_by_field'] == 'source_id'
                assert kwargs['group_size'] == 3
                assert kwargs['strict_group_size'] is False
                assert kwargs['limit'] == 100
                return [[{'entity': {'source_id': 'long', 'chunk': 7, 'text': 'actual project'}, 'distance': .9},
                         {'entity': {'source_id': 'other', 'chunk': 3, 'text': 'second project'}, 'distance': .8}]]
            assert 'group_by_field' not in kwargs
            return [[]]
        def close(self): pass
    index = MilvusIndex()
    async def embed(texts): return [[.1, .2]]
    monkeypatch.setattr(index, 'embed', embed)
    monkeypatch.setattr(index, 'client', lambda: Client())
    result = asyncio.run(index.search('project', allowed_ids=['long', 'other'], org_id='o', kind='talent'))
    assert result[0]['chunk'] == 7 and result[1]['source_id'] == 'other'
    asyncio.run(index.search('policy', allowed_ids=['d'], org_id='o', kind='knowledge'))


def test_versions_capture_model_digests_app_and_prompt(monkeypatch):
    values = {'CHAT_MODEL_DIGEST': 'chat-sha', 'EMBEDDING_MODEL_DIGEST': 'embed-sha', 'DIFY_APP_ID': 'app-id', 'PROMPT_VERSION': 'prompt-v7'}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    snapshot = platform(Responses({})).versions()
    assert snapshot['chat_model_digest'] == 'chat-sha'
    assert snapshot['embedding_model_digest'] == 'embed-sha'
    assert snapshot['dify_app_id'] == 'app-id'
    assert snapshot['prompt_version'] == 'prompt-v7'
