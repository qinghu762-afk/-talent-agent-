import asyncio
import pytest
from talent_platform.analysis import AnalyticsEngine


@pytest.mark.parametrize('invalid,feedback', [
    ("SELECT COUNT(*) FROM analytics_talents WHERE org_id=current_setting('app.org_id')", 'CURRENT_SETTING'),
    ("SELECT id FROM analytics_talents WHERE id='unterminated", 'SQL parse failed'),
])
def test_invalid_generated_sql_gets_bounded_feedback_before_query_execution(invalid, feedback):
    calls, queries = [], []
    async def model(request, actor):
        calls.append(request)
        if request['task'] == 'analysis_answer':
            return {'answer': '授权范围有2条记录'}
        if len(calls) == 1:
            return {'sql': invalid}
        assert feedback in request['validation_feedback']
        return {'sql': 'SELECT COUNT(*) AS count FROM analytics_talents'}
    async def runner(sql, dialect):
        queries.append(sql)
        return {'columns': ['count'], 'rows': [[2]]}
    result = asyncio.run(AnalyticsEngine(model=model, runner=runner).execute(
        {'question': '本组织人才数量', 'allowed_fields': ['analytics_talents.id'],
         'allowed_tables': ['analytics_talents'], 'allowed_org_ids': ['o']},
        actor={'id': 'u', 'org_id': 'o', 'role': 'manager'}))
    assert result['rows'] == [[2]] and len(queries) == 1
    assert "'o'" in queries[0]
