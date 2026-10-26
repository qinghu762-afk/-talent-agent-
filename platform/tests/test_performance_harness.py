"""Pure safety/scoring checks; these tests never connect to a service."""
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
from talent_platform.ai_domain import score_candidate


@pytest.fixture
def harness():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / 'tools' / 'performance.py'))


def test_explicit_count_execute_and_output_confinement(harness):
    validate = harness['validate_options']
    good = dict(count=10000, batch_size=64, execute=True, org_id='o', actor_id='a',
                output='/data/verification/performance.json')
    validate(SimpleNamespace(**good))
    for changes in ({'count': 0}, {'count': 10001}, {'execute': False}, {'org_id': ''},
                    {'actor_id': ''}, {'batch_size': 1000}, {'output': '/data/other.json'},
                    {'output': '/data/verification/../secret.json'}):
        with pytest.raises(ValueError):
            validate(SimpleNamespace(**{**good, **changes}))


def test_scope_refuses_real_org_and_cross_org_inactive_or_employee(harness):
    validate = harness['validate_scope']
    org = {'id': 'o', 'kind': 'organizations', 'data': {'name': 'SYNTHETIC benchmark'}}
    actor = {'id': 'a', 'org_id': 'o', 'role': 'hr', 'active': 1}
    validate(org, actor, org_id='o', actor_id='a')
    validate({**org, 'data': {'name': '合成性能测试'}}, actor, org_id='o', actor_id='a')
    for unsafe_org, unsafe_actor in [
        ({**org, 'data': {'name': '正式人事组织', 'synthetic': True}}, actor),
        (org, {**actor, 'org_id': 'other'}), (org, {**actor, 'active': 0}),
        (org, {**actor, 'role': 'employee'}), (None, actor), (org, None),
    ]:
        with pytest.raises(ValueError):
            validate(unsafe_org, unsafe_actor, org_id='o', actor_id='a')


def test_record_and_vector_collision_refusal(harness):
    expected = harness['record_spec']('o', 'a', 0)
    validate_record = harness['validate_record_collision']
    validate_record(None, expected)
    validate_record({**expected, 'indexed_revision': 1}, expected)
    for changes in ({'org_id': 'real'}, {'owner_id': 'other'}, {'kind': 'knowledge'},
                    {'revision': 2}, {'data': {'profile': expected['data']['profile']}}):
        with pytest.raises(ValueError):
            validate_record({**expected, **changes}, expected)
    row = harness['vector_metadata'](expected, 0, 'bge-m3')
    harness['validate_vector_collision'](row, {row['id']: row})
    for changes in ({'benchmark': None}, {'source_id': 'real'}, {'org_id': 'real'},
                    {'owner_id': 'real'}, {'text': 'existing nonbenchmark text'}):
        with pytest.raises(ValueError):
            harness['validate_vector_collision']({**row, **changes}, {row['id']: row})


def test_uuid_and_profiles_are_reproducible_and_scoring_recomputed(harness):
    spec = harness['record_spec']('o', 'a', 1)
    assert spec == harness['record_spec']('o', 'a', 1)
    assert spec['id'] != harness['record_spec']('other', 'a', 1)['id']
    requirements = harness['job_requirements']()
    metadata = harness['vector_metadata'](spec, 0, 'bge-m3')
    hit = {**metadata, 'semantic_score': .83}
    profile = spec['data']['profile']
    score = score_candidate(requirements, profile, [hit])
    snapshot = {**spec, 'profile': profile, 'indexed_revision': 1, 'index_model': 'bge-m3'}
    candidate = {'talent_id': spec['id'], 'revision': 1, 'profile': profile, 'score': score}
    result = {'candidates': [candidate], 'diagnostics': {'authorized': 1, 'hard_eligible': 1,
                                                       'recall_limit': 100, 'output_limit': 20}}
    harness['validate_match_result'](result, [snapshot], requirements)
    assert score['eligible'] and all(item['status'] == 'pass' for item in score['conditions'])
    assert {c['name'] for c in score['conditions']} >= {'skill:Python', 'experience', 'education', 'location'}
    assert score['verified_related_experience_months'] >= 24
    assert score['dimensions']['projects']['score'] == 83
    for bad in ({**result, 'candidates': [candidate] * 21},
                {**result, 'candidates': [{**candidate, 'score': {**score, 'total': 1}}]},
                {**result, 'candidates': [{**candidate, 'talent_id': 'unauthorized'}]},
                {**result, 'candidates': []}):
        with pytest.raises(ValueError):
            harness['validate_match_result'](bad, [snapshot], requirements)
