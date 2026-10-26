
import pytest
from test_ai import Responses, platform, run


def facts(**values):
    evidence = []
    for field, value in values.items():
        for item in value if isinstance(value, list) else [value]:
            quote = ' '.join(str(v) for v in item.values()) if isinstance(item, dict) else str(item)
            evidence.append({'field': field, 'value': item, 'quote': quote})
    return {'profile': {**values, 'evidence': evidence}}


def test_missing_core_fields_trigger_retry_and_merge_verified_facts():
    model = Responses(facts(name='张三', skills=['Python']),
                      facts(phone='13800138000', education=[{'degree': '本科'}]))
    result = run(platform(model), 'resume', {'text': '姓名张三\nPython\n电话13800138000\n本科'})
    assert result['profile']['name'] == '张三'
    assert result['profile']['skills'] == ['Python']
    assert result['profile']['phone'] == '13800138000'
    assert result['report']['quality_status'] == 'complete'
    assert result['report']['missing_fields'] == []
    assert result['report']['retry_count'] == 1
    assert result['report']['stop_reason'] == 'core_fields_complete'
    assert model.calls[1]['missing_fields'] == ['contact', 'education_or_experiences']


def test_partial_resume_stops_after_valid_round_adds_no_facts():
    model = Responses(facts(name='张三', skills=['Python']))
    result = run(platform(model), 'resume', {'text': '张三 Python'})
    assert len(model.calls) == 2
    assert result['report']['quality_status'] == 'partial'
    assert result['report']['stop_reason'] == 'no_progress'
    assert result['report']['missing_fields'] == ['contact', 'education_or_experiences']


def test_conflicting_later_fact_preserves_first_verified_identity():
    model = Responses(facts(name='张三'), facts(name='李四', phone='13800138000', skills=['Python'], education=['本科']))
    result = run(platform(model), 'resume', {'text': '姓名张三\n姓名李四\n13800138000\nPython\n本科'})
    assert result['profile']['name'] == '张三'
    assert 'conflicting:name' in result['report']['issues']
    assert result['report']['needs_review'] is True


def test_no_grounded_facts_is_failure_after_no_progress():
    model = Responses({'profile': {}})
    with pytest.raises(ValueError, match='grounded facts'):
        run(platform(model), 'resume', {'text': '无可识别内容'})
    assert len(model.calls) == 2


def test_format_errors_exhaust_document_retry_budget():
    model = Responses({'invalid': True})
    with pytest.raises(ValueError, match='grounded facts'):
        run(platform(model), 'resume', {'text': '无可识别内容'})
    assert len(model.calls) == 4


def test_long_resume_splits_input_and_extracts_facts_from_late_chunk():
    calls = []
    async def model(request):
        calls.append(request)
        if '13800138000' in request['text']:
            return facts(phone='13800138000', education=['本科'])
        return facts(name='张三', skills=['Python'])
    text = '张三 Python\n' + ('项目说明。' * 4000) + '\n13800138000 本科'
    result = run(platform(model), 'resume', {'text': text})
    assert result['report']['quality_status'] == 'complete'
    assert len(calls) > 1
    assert max(len(call['text']) for call in calls) <= 12000


def test_transient_model_exception_is_not_format_retry():
    from talent_platform.ai import AIUnavailable
    async def model(request):
        raise AIUnavailable('timeout')
    with pytest.raises(AIUnavailable):
        run(platform(model), 'resume', {'text': '张三'})


def test_three_supplement_rounds_are_document_budget_even_when_each_adds_fact():
    model = Responses(facts(name='张三'), facts(skills=['Python']), facts(phone='13800138000'), facts(location='北京'))
    result = run(platform(model), 'resume', {'text': '张三 Python 13800138000 北京'})
    assert result['report']['rounds'] == 4
    assert result['report']['retry_count'] == 3
    assert result['report']['stop_reason'] == 'retry_budget_exhausted'
    assert result['report']['missing_fields'] == ['education_or_experiences']


def test_invalid_nested_evidence_consumes_budget_instead_of_crashing():
    model = Responses({'profile': {'name': '张三', 'evidence': 'invalid'}})
    with pytest.raises(ValueError, match='grounded facts'):
        run(platform(model), 'resume', {'text': '张三'})
    assert len(model.calls) == 4


def test_normalized_contact_retains_verifiable_original_evidence():
    from talent_platform.ai_domain import verified_values
    model = Responses(facts(name='张三', phone='+86 138 0013 8000', skills=['Python'], education=['本科']))
    result = run(platform(model), 'resume', {'text': '张三 +86 138 0013 8000 Python 本科'})
    assert verified_values(result['profile'], 'phone') == ['13800138000']


def test_empty_structure_cannot_count_as_grounded_education():
    model = Responses({'profile': {'education': [{}], 'evidence': [{'field': 'education', 'value': {}, 'quote': '本科'}]}})
    with pytest.raises(ValueError, match='grounded facts'):
        run(platform(model), 'resume', {'text': '本科'})


def test_reexecuting_run_cannot_reuse_facts_from_another_document():
    model = Responses(facts(name='张三', skills=['Python']), {'profile': {}})
    service = platform(model)
    # Use independent calls with the same checkpoint identity, as a worker retry does.
    result = run(service, 'resume', {'text': '张三 Python'})
    assert result['profile']['name'] == '张三'
    with pytest.raises(ValueError, match='grounded facts'):
        run(service, 'resume', {'text': '无可识别内容'})
