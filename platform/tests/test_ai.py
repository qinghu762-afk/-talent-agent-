import asyncio
import importlib
import io
import zipfile

import pytest


def ai_module():
    spec = importlib.util.find_spec('talent_platform.ai')
    assert spec is not None, 'new AI implementation is required'
    return importlib.import_module('talent_platform.ai')


class Responses:
    def __init__(self, *values):
        self.values = list(values)
        self.calls = []

    async def __call__(self, request):
        self.calls.append(request)
        return self.values[min(len(self.calls)-1, len(self.values)-1)]


def platform(model=None, vectors=None):
    from langgraph.checkpoint.memory import InMemorySaver
    return ai_module().AIPlatform(model=model, vectors=vectors, checkpointer=InMemorySaver())


def run(service, kind, payload):
    return asyncio.run(service.execute(kind, payload, run_id='test', actor={'id': 'u', 'org_id': 'o', 'role': 'hr'}))


def test_resume_rejects_invented_identity_without_any_verified_facts():
    model = Responses({'profile': {'name': 'Alice', 'phone': '13800000000', 'skills': ['Python'], 'evidence': []}})
    with pytest.raises(ValueError, match='grounded facts'):
        run(platform(model), 'resume', {'text': 'Alice 使用 Python 完成项目'})
    assert len(model.calls) == 2


def test_resume_normalizes_only_grounded_facts():
    model = Responses({'profile': {'name': '张三', 'skills': [' python ', 'Python'], 'evidence': [
        {'field': 'name', 'value': '张三', 'quote': '张三'},
        {'field': 'skills', 'value': 'python', 'quote': 'Python'}]}})
    result = run(platform(model), 'resume', {'text': '张三\nPython'})
    assert result['profile']['name'] == '张三'
    assert result['profile']['skills'] == ['Python']
    assert len(model.calls) == 2
    assert result['report']['quality_status'] == 'partial'


def test_matching_uses_hits_and_verified_experience_without_unknown_segment_penalty():
    from talent_platform.ai_domain import score_candidate
    profile = {'source': 'manual', 'verified_by': 'hr', 'skills': ['Python'], 'experiences': [{'role': 'Python工程师', 'start': '2020-01', 'end': '2025-01'}, {'start': None, 'end': None}], 'education': []}
    hits = [{'text': 'Python', 'source_id': 't', 'chunk': 0}]
    score = score_candidate({'required_skills': ['Python'], 'min_experience_months': 48}, profile, hits)
    assert score['eligible'] is True
    assert score['total'] == 100
    assert score['unknowns']
    assert score['dimensions']['skills']['weight'] == 0.4
    assert score_candidate({}, profile, hits)['eligible'] is False
    assert score_candidate({'required_skills': ['Java']}, profile, hits)['eligible'] is False


def test_chat_omits_foreign_private_documents_and_rejects_forged_citations():
    model = Responses({'answer': 'secret', 'citations': [{'source_id': 'foreign', 'quote': 'secret'}]})
    result = run(platform(model), 'chat', {'question': 'secret', 'documents': [
        {'id': 'foreign', 'title': 'x', 'text': 'secret', 'scope': 'private', 'org_id': 'o', 'owner_id': 'another'}], 'history': [], 'session_id': 's'})
    assert result['citations'] == []
    assert '依据' in result['answer']
    assert not model.calls


def test_training_cannot_recommend_courses_outside_authorized_catalog():
    model = Responses({'title': '学习计划', 'course_ids': ['secret'], 'reasons': {'secret': 'x'}})
    with pytest.raises(ValueError, match='course'):
        run(platform(model), 'training', {'talent': {}, 'courses': [{'id': 'public', 'title': 'Python'}]})


def test_assessment_scores_objective_answers_and_bounds_subjective_rubric():
    model = Responses({'scores': [{'question_id': 'q2', 'points': 999, 'feedback': 'x'}]})
    result = run(platform(model), 'assessment', {'questions': [
        {'id': 'q1', 'question_type': 'multiple', 'answer': ['A', 'B'], 'points': 5, 'skills': ['Python']},
        {'id': 'q2', 'question_type': 'text', 'rubric': '最多 5 分', 'points': 5, 'skills': ['Python']}],
        'answers': {'q1': ['B', 'A'], 'q2': 'answer'}, 'events': []})
    assert result['total'] == 100
    assert result['dimensions']['Python'] == 100
    assert result['inference'] is True


def test_sql_scopes_each_table_and_rejects_exfiltration():
    from talent_platform.analysis import validate_sql
    sql = validate_sql('SELECT name FROM analytics_talents', dialect='postgres', allowed_org_ids=['o'], allowed_fields=['name'], allowed_tables=['analytics_talents'])
    assert 'org_id' in sql and "'o'" in sql and 'LIMIT 200' in sql
    for bad in ['DELETE FROM analytics_talents', 'SELECT password FROM analytics_talents', 'SELECT pg_sleep(10) FROM analytics_talents', 'SELECT name FROM analytics_talents; SELECT 1', 'SELECT * FROM analytics_talents']:
        with pytest.raises(ValueError):
            validate_sql(bad, dialect='postgres', allowed_org_ids=['o'], allowed_fields=['name'], allowed_tables=['analytics_talents'])


def test_safe_report_never_creates_external_relationships_or_interprets_html():
    from talent_platform.reports import render_report
    result = {'answer': '<img src="file:///etc/passwd">\x00 & 中文', 'sql': 'SELECT 1', 'columns': ['name'], 'rows': [['张三']]}
    data = render_report(result, 'docx')
    with zipfile.ZipFile(io.BytesIO(data)) as doc:
        assert b'TargetMode="External"' not in b''.join(doc.read(n) for n in doc.namelist() if n.endswith('.rels'))
        assert b'&lt;img' in doc.read('word/document.xml')
    assert render_report(result, 'pdf').startswith(b'%PDF')


def test_workflow_gateway_uses_deployed_dify_inputs_and_never_falls_back(monkeypatch):
    import httpx
    from talent_platform.ai import DifyGateway
    monkeypatch.setenv('DIFY_API_URL', 'http://dify/v1')
    monkeypatch.setenv('DIFY_APP_KEY', 'test')
    monkeypatch.setenv('DIFY_APP_MODE', 'workflow')
    original = httpx.AsyncClient
    def respond(request):
        import json
        body = json.loads(request.content)
        assert request.url.path == '/v1/workflows/run'
        assert body['inputs']['prompt']
        return httpx.Response(200, json={'data': {'status': 'succeeded', 'outputs': {'text': '{"profile": {"name": "张三"}}'}}})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    result = asyncio.run(DifyGateway()({'task': 'resume'}))
    assert result['profile']['name'] == '张三'


def test_delete_index_removes_only_org_bound_source():
    class Vectors:
        async def delete(self, *, source_id, org_id, kind):
            assert source_id == 'deleted' and org_id == 'o' and kind == 'talent'
            return {'deleted': True, 'source_id': source_id}
    result = run(platform(Responses({}), Vectors()), 'delete_index', {'id': 'deleted', 'kind': 'talent'})
    assert result['deleted'] is True


def test_approval_interrupt_resumes_original_authorized_snapshot():
    model = Responses({'title': '学习', 'course_ids': ['c'], 'reasons': {'c': '技能差距'}})
    service = platform(model)
    result = run(service, 'training', {'approval_required': True, 'courses': [{'id': 'c'}]})
    assert result['status'] == 'awaiting_approval'
    assert model.calls == []
    result = run(service, 'training', {'approval_decision': True, 'courses': [{'id': 'secret'}]})
    assert result['course_ids'] == ['c']


def test_internal_service_rejects_missing_or_wrong_key(monkeypatch):
    from fastapi.testclient import TestClient
    from talent_platform.ai_service import create_app
    monkeypatch.setenv('INTERNAL_SERVICE_KEY', 'test-secret')
    body = {'kind': 'resume', 'payload': {'text': 'hello'}, 'run_id': 'r', 'actor': {'id': 'u', 'org_id': 'o'}}
    client = TestClient(create_app(platform=platform(Responses({'profile': {}}))))
    assert client.post('/execute', json=body).status_code == 401
    assert client.post('/execute', json=body, headers={'X-Service-Key': 'wrong'}).status_code == 401
    analytics = TestClient(create_app(platform=platform(), analytics_only=True))
    assert analytics.post('/execute', json=body, headers={'X-Service-Key': 'test-secret'}).status_code == 403


def test_match_discards_stale_or_unauthorized_vector_hits():
    class Vectors:
        async def search(self, query, **scope):
            assert scope['allowed_ids'] == ['t'] and scope['limit'] == 100
            return [{'source_id': 't', 'revision': 1, 'text': 'Python', 'index_model': 'e', 'chunk': 0},
                    {'source_id': 'secret', 'revision': 2, 'text': 'Python', 'index_model': 'e', 'chunk': 0}]
    result = run(platform(Responses({}), Vectors()), 'match', {'job': {'requirements': {'required_skills': ['Python']}},
        'talents': [{'id': 't', 'org_id': 'o', 'revision': 2, 'indexed_revision': 2, 'index_model': 'e', 'profile': {'source': 'manual', 'verified_by': 'hr', 'skills': ['Python']}}], 'allowed_ids': ['t']})
    assert result['candidates'] == []


def test_sql_scopes_both_join_sides_and_rejects_unsafe_cte_and_catalogs():
    from talent_platform.analysis import validate_sql
    options = {'dialect': 'postgres', 'allowed_org_ids': ['o'], 'allowed_fields': ['id', 'name', 'talent_id', 'total'],
               'allowed_tables': ['analytics_talents', 'analytics_assessments']}
    sql = validate_sql('SELECT t.name, a.total FROM analytics_talents t LEFT JOIN analytics_assessments a ON t.id=a.talent_id', **options)
    assert sql.count("org_id IN ('o')") == 2
    for unsafe in ['WITH x AS (DELETE FROM analytics_talents RETURNING id) SELECT id FROM x',
                   'SELECT name FROM public.analytics_talents', 'SELECT name FROM analytics_talents FOR UPDATE',
                   'SELECT name FROM analytics_talents UNION SELECT name FROM analytics_talents']:
        with pytest.raises(ValueError):
            validate_sql(unsafe, **options)


def test_rag_returns_only_exact_authorized_chunk_quotes():
    class Vectors:
        async def search(self, query, **scope):
            return [{'source_id': 'd', 'chunk': 0, 'semantic_score': .9}]
    model = Responses({'order': [0]}, {'answer': '政策依据：年假五天', 'citations': [{'source_id': 'd', 'quote': '年假五天'}]})
    result = run(platform(model, Vectors()), 'chat', {'question': '年假', 'documents': [{'id': 'd', 'title': '制度', 'org_id': 'o',
        'scope': 'org', 'text': '年假五天'}], 'history': [{'role': 'user', 'content': 'previous'}], 'session_id': 's'})
    assert result['citations'] == [{'source_id': 'd', 'title': '制度', 'quote': '年假五天'}]
    assert model.calls[-1]['history'] == [{'role': 'user', 'content': 'previous'}]


def test_empty_extraction_cannot_be_reported_as_verified():
    with pytest.raises(ValueError, match='grounded facts'):
        run(platform(Responses({'profile': {}})), 'resume', {'text': '无可识别的内容'})


def test_duplicate_detection_is_permission_scoped_and_never_auto_merges():
    class Vectors:
        async def search(self, query, **scope):
            assert scope['allowed_ids'] == ['other']
            return [{'source_id': 'other', 'semantic_score': .96, 'revision': 3, 'text': '同一经历', 'chunk': 0},
                    {'source_id': 'secret', 'semantic_score': 1.0, 'revision': 1, 'text': 'secret', 'chunk': 0}]
    result = run(platform(Responses({}), Vectors()), 'duplicates', {'talent': {'id': 'self', 'org_id': 'o', 'profile': {'name': '张三'}},
                     'allowed_ids': ['self', 'other']})
    assert result['auto_merged'] is False
    assert [x['talent_id'] for x in result['suspected_duplicates']] == ['other']


def test_analysis_uses_vanna_generation_and_validates_before_readonly_runner():
    from talent_platform.analysis import AnalyticsEngine
    async def model(request, actor):
        if request['task'] == 'analysis_sql':
            assert request['messages'], 'Vanna must supply the schema-grounded SQL prompt'
            return {'sql': 'SELECT name FROM analytics_talents'}
        return {'answer': '组织内有张三'}
    async def reader(sql, dialect):
        assert "org_id IN ('o')" in sql
        return {'columns': ['name'], 'rows': [['张三']]}
    engine = AnalyticsEngine(model=model, runner=reader)
    result = asyncio.run(engine.execute({'question': '员工姓名', 'datasource': 'postgres', 'allowed_org_ids': ['o'],
                        'allowed_fields': ['name']}, actor={'id': 'u', 'org_id': 'o', 'role': 'hr'}))
    assert result['rows'] == [['张三']]


def test_job_cannot_bind_invented_constraint_to_unrelated_real_quote():
    model = Responses({'requirements': {'required_skills': ['Java'], 'evidence': [
        {'field': 'required_skills', 'value': 'Java', 'quote': 'Python'}]}})
    with pytest.raises(ValueError, match='evidence'):
        run(platform(model), 'job', {'description': '要求 Python'})


def test_analysis_projects_only_real_columns_per_view_with_union_permissions():
    from talent_platform.analysis import validate_sql
    sql = validate_sql('SELECT name FROM analytics_talents', dialect='postgres', allowed_org_ids=['o'],
                       allowed_fields=['name', 'title', 'total', 'progress'], allowed_tables=['analytics_talents'])
    assert 'title' not in sql and 'total' not in sql and 'progress' not in sql


def test_invalid_structured_response_consumes_resume_retry_budget():
    model = Responses({'wrong': []}, {'profile': {'name': '张三', 'evidence': [{'field': 'name', 'value': '张三', 'quote': '张三'}]}})
    result = run(platform(model), 'resume', {'text': '张三'})
    assert len(model.calls) == 3
    assert result['profile']['name'] == '张三'
    assert result['report']['needs_review'] is True
    assert result['report']['quality_status'] == 'partial'


def test_resume_schema_failure_exhausts_budget_without_fabrication():
    model = Responses({'wrong': []})
    with pytest.raises(ValueError, match='grounded facts'):
        run(platform(model), 'resume', {'text': '不确定'})
    assert len(model.calls) == 4


def test_model_unavailable_does_not_become_resume_empty_success():
    from talent_platform.ai import AIUnavailable
    async def missing(request):
        raise AIUnavailable('Dify is unavailable')
    with pytest.raises(AIUnavailable):
        run(platform(missing), 'resume', {'text': '张三'})


def test_matching_skill_evidence_cannot_substitute_javascript_for_java():
    from talent_platform.ai_domain import score_candidate
    result = score_candidate({'required_skills': ['Java']}, {'source': 'manual', 'verified_by': 'hr', 'skills': ['Java', 'JavaScript']},
                             [{'source_id': 't', 'chunk': 1, 'text': '负责 JavaScript 前端开发'}])
    assert result['eligible'] is False


def test_reindex_removes_obsolete_revisions_and_tail_chunks(monkeypatch):
    from talent_platform.ai import MilvusIndex
    class Client:
        rows = []
        def has_collection(self, collection): return True
        def upsert(self, collection, rows): self.rows.extend(rows)
        def delete(self, collection, *, filter):
            assert 'revision' in filter and 'chunk' in filter and 'org_id' in filter
            self.rows[:] = [row for row in self.rows if row['revision'] == 2 and row['chunk'] < 1]
        def close(self): pass
    client = Client()
    client.rows = [{'revision': 1, 'chunk': 0}, {'revision': 2, 'chunk': 10}]
    index = MilvusIndex()
    async def embed(texts): return [[.1, .2] for _ in texts]
    monkeypatch.setattr(index, 'embed', embed)
    monkeypatch.setattr(index, 'client', lambda: client)
    asyncio.run(index.upsert({'id': 't', 'org_id': 'o', 'revision': 2, 'text': 'Python'}, kind='talent'))
    assert len(client.rows) == 1
    assert client.rows[0]['text'] == 'Python'


def test_qualified_column_permissions_allow_safe_single_table_unqualified_sql():
    from talent_platform.analysis import validate_sql
    result = validate_sql('SELECT name FROM analytics_talents', dialect='postgres', allowed_org_ids=['o'],
                         allowed_fields=['analytics_talents.name'], allowed_tables=['analytics_talents'])
    assert "org_id IN ('o')" in result
    with pytest.raises(ValueError):
        validate_sql('SELECT title FROM analytics_talents', dialect='postgres', allowed_org_ids=['o'],
                     allowed_fields=['analytics_jobs.title'], allowed_tables=['analytics_talents'])


@pytest.mark.parametrize('field,value,text,want', [
    ('skills', 'Python', '不熟悉Python', False),
    ('skills', 'Python', 'no experience with Python', False),
    ('skills', 'Python', 'never used Python', False),
    ('skills', 'Python', 'lack Python experience', False),
    ('skills', 'Python', '尚未学习Python', False),
    ('skills', 'Python', '熟练Python', True),
    ('skills', 'Python', 'used Python', True),
    ('name', '张三', '推荐人：张三', False),
    ('name', '张三', '姓名：张三', True),
    ('phone', '1234567', '电话1234567', False),
    ('phone', '13800138000', '电话13800138000', True),
    ('phone', '12345678901', '电话12345678901', False),
    ('phone', '+12025550123', '电话+12025550123', True),
    ('phone', '010-12345678', '电话010-12345678', True),
    ('email', 'test@example.com', '邮箱test@example.com', True),
    ('email', 'bad@@example.com', '邮箱bad@@example.com', False),
    ('email', 'test@example', '邮箱test@example', False),
    ('location', '北京', '不在北京', False),
    ('certificates', 'PMP', '没有PMP', False),
    ('certificates', 'PMP', '拥有PMP', True),
    ('skills', 'Java', 'JavaScript', False),
    ('skills', 'SQL', 'MySQL', False),
    ('skills', 'Java', '负责Java开发', True),
    ('name', '李四', '姓名张三', False),
    ('phone', '１３８００１３８０００', '１３８００１３８０００', True),
    ('phone', '+86 138 0013 8000', '+86 138 0013 8000', True),
    ('email', 'Test@Example.com', 'Test@Example.com', True),
    ('location', '上海', '期望工作地上海', False),
    ('certificates', 'PMP', 'PMP备考中', False),
    ('skills', 'Python', 'Python（计划学习）', False),
])
def test_thirty_resume_claim_boundaries(field, value, text, want):
    from talent_platform.ai_domain import ground_profile
    listed = field in {'skills', 'certificates'}
    raw = {field: [value] if listed else value, 'evidence': [{'field': field, 'value': value, 'quote': value}]}
    profile, _ = ground_profile(raw, text)
    assert bool(profile[field]) is want


@pytest.mark.parametrize('requirements,profile,hits,want', [
    ({'required_skills': ['Python']}, {'source': 'manual', 'verified_by': 'hr', 'skills': ['Python']}, [{'text': 'Python项目'}], True),
    ({'required_skills': ['Python'], 'responsibilities': ['带领跨职能团队']}, {'source': 'manual', 'verified_by': 'hr', 'skills': ['Python']}, [{'text': 'Python项目'}], True),
    ({}, {'source': 'manual', 'verified_by': 'hr', 'skills': ['Python']}, [{'text': 'Python项目'}], False),
    ({'required_skills': ['Python']}, {'skills': ['Python']}, [{'text': 'Python项目'}], False),
    ({'min_experience_months': 48}, {'source': 'manual', 'verified_by': 'hr', 'experiences': [{'start': '2020-01', 'end': '2025-01'}, {'start': None, 'end': None}]}, [{'text': '项目经历'}], True),
])
def test_five_labeled_job_acceptance_cases(requirements, profile, hits, want):
    from talent_platform.ai_domain import score_candidate
    assert score_candidate(requirements, profile, hits)['eligible'] is want
