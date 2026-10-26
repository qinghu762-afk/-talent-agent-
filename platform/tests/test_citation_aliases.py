from test_ai import Responses, platform, run


class NoVectors:
    async def search(self, *args, **kwargs):
        return []


def test_model_uses_short_context_ids_and_server_restores_exact_source_id():
    source_id = '5e030cb9-3d17-4af6-878a-779adc211b14'
    model = Responses({'order': [0]}, {'answer': '两门', 'citations': [{'source_id': 'S1', 'quote': '员工培训两门Python课程'}]})
    result = run(platform(model, NoVectors()), 'chat', {'question': 'Python', 'documents': [{'id': source_id, 'org_id': 'o', 'text': '员工培训两门Python课程', 'title': '合成制度'}]})
    assert model.calls[-1]['context'][0]['source_id'] == 'S1'
    assert source_id not in str(model.calls[-1]['context'])
    assert result['citations'][0]['source_id'] == source_id


def test_alias_does_not_allow_a_quote_from_a_different_context_source():
    model = Responses({'order': [0, 1]}, {'answer': '错误串引', 'citations': [{'source_id': 'S1', 'quote': '另一份Python原文'}]})
    result = run(platform(model, NoVectors()), 'chat', {'question': 'Python', 'documents': [
        {'id': 'first', 'org_id': 'o', 'text': '第一份Python原文', 'title': '第一份'},
        {'id': 'second', 'org_id': 'o', 'text': '另一份Python原文', 'title': '第二份'}]})
    assert result['citations'] == []
