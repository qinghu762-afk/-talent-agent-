import pytest
from talent_platform.ai_domain import score_candidate


def profile(*, projects=True, bonus=True):
    return {'source': 'manual', 'verified_by': 'hr', 'skills': ['Python', 'SQL'] if bonus else ['Python'],
            'education': [{'degree': '本科'}], 'location': '上海', 'certificates': ['PMP'],
            'experiences': [{'company': '甲公司', 'role': 'Python工程师', 'start': '2020-01', 'end': '2025-01'}, {'start': None, 'end': None}],
            'projects': [{'name': '采购系统', 'description': 'Python自动审批'}] if projects else []}


def requirements():
    return {'required_skills': ['Python'], 'preferred_skills': ['SQL'], 'min_experience_months': 48,
            'min_education': '本科', 'location': '上海', 'required_certificates': ['PMP'], 'responsibilities': ['采购审批系统开发']}


@pytest.mark.parametrize('candidate,hits,want', [
    (profile(), [{'source_id': 'a', 'chunk': 4, 'semantic_score': .9, 'text': '项目 采购系统 Python自动审批 SQL'}], 97.5),
    (profile(), [{'source_id': 'b', 'chunk': 1, 'semantic_score': .99, 'text': '技能 Python SQL'}], 75),
    (profile(projects=False), [{'source_id': 'c', 'chunk': 2, 'semantic_score': .99, 'text': '项目 采购系统 Python自动审批 SQL'}], 75),
    (profile(bonus=False), [{'source_id': 'd', 'chunk': 5, 'semantic_score': .8, 'text': '项目 采购系统 Python自动审批'}], 85),
])
def test_prelabelled_project_evidence_distinguishes_candidates(candidate, hits, want):
    score = score_candidate(requirements(), candidate, hits)
    assert score['eligible'] is True
    assert score['total'] == want
    assert set(score['dimensions']) == {'skills', 'experience', 'projects', 'bonus'}
    assert {key: value['weight'] for key, value in score['dimensions'].items()} == {'skills': .4, 'experience': .25, 'projects': .25, 'bonus': .1}
    assert score['verified_experience_months'] == 60


def test_project_explanation_uses_same_bound_chunk_and_actual_similarity():
    hits = [{'source_id': 'a', 'chunk': 3, 'semantic_score': .4, 'text': '项目 采购系统 Python自动审批 SQL'},
            {'source_id': 'a', 'chunk': 9, 'semantic_score': .99, 'text': '技能 Python SQL'}]
    score = score_candidate(requirements(), profile(), hits)
    assert score['dimensions']['projects']['score'] == 40
    assert score['project_evidence'][0]['chunk'] == 3
    assert score['project_evidence'][0]['semantic_score'] == .4
    assert score['project_evidence'][0]['project']['name'] == '采购系统'
    assert score['project_evidence'][0]['inference'] is True


def test_project_without_grounding_or_similarity_is_zero():
    unverified = {**profile(), 'source': 'model', 'evidence': []}
    req = {'responsibilities': ['采购审批系统开发']}
    hit = {'source_id': 'a', 'chunk': 3, 'semantic_score': .9, 'text': '项目 采购系统 Python自动审批'}
    assert score_candidate(req, unverified, [hit])['dimensions']['projects']['score'] == 0
    assert score_candidate(req, profile(), [{**hit, 'semantic_score': None}])['dimensions']['projects']['score'] == 0


def test_education_location_and_required_certificates_do_not_create_scoring_dimensions():
    score = score_candidate({'min_education': '本科', 'location': '上海', 'required_certificates': ['PMP']}, profile(), [])
    assert score['eligible'] is False
    assert all(value['score'] is None for value in score['dimensions'].values())


def test_unconfigured_dimensions_are_renormalized_and_preferred_skills_are_bonus():
    score = score_candidate({'required_skills': ['Python'], 'preferred_skills': ['SQL']}, profile(), [{'text': 'Python'}])
    assert score['total'] == 80
    assert score['dimensions']['skills']['normalized_weight'] == .8
    assert score['dimensions']['bonus']['normalized_weight'] == .2
    assert score['dimensions']['experience']['score'] is None
    assert score['dimensions']['projects']['score'] is None


def test_unrelated_verified_tenure_passes_years_gate_but_scores_no_related_experience():
    candidate = profile()
    candidate['experiences'] = [{'role': '园艺师', 'start': '2020-01', 'end': '2025-01'}]
    score = score_candidate({'required_skills': ['Python'], 'min_experience_months': 48}, candidate, [{'text': 'Python'}])
    assert score['eligible'] is True
    assert score['dimensions']['experience']['score'] == 0
    assert score['verified_experience_months'] == 60
    assert score['verified_related_experience_months'] == 0


def test_related_intervals_are_unioned_and_unknown_segment_does_not_reduce_them():
    candidate = profile()
    candidate['experiences'] = [{'role': 'Python工程师', 'start': '2020-01', 'end': '2023-01'},
                                {'role': 'Python工程师', 'start': '2022-01', 'end': '2025-01'},
                                {'role': 'Python工程师', 'start': None, 'end': None}]
    score = score_candidate({'required_skills': ['Python'], 'min_experience_months': 48}, candidate, [{'text': 'Python'}])
    assert score['verified_related_experience_months'] == 60
    assert score['dimensions']['experience']['score'] == 100


def test_project_values_cannot_be_borrowed_across_two_projects_inside_one_chunk():
    score = score_candidate({'responsibilities': ['采购系统开发']}, profile(),
                            [{'source_id': 't', 'chunk': 0, 'semantic_score': .99,
                              'text': '项目 采购系统 采用Java开发；另一个项目 物流系统 Python自动审批'}])
    assert score['dimensions']['projects']['score'] == 0


def test_grounded_project_source_quote_is_preserved_on_exact_hit_explanation():
    from talent_platform.ai_domain import ground_profile
    record = {'name': '采购系统', 'description': 'Python自动审批'}
    source_quote = '采购系统 Python自动审批'
    candidate, _ = ground_profile({'projects': [record], 'evidence': [
        {'field': 'projects', 'value': record, 'quote': source_quote}]}, '项目 ' + source_quote)
    score = score_candidate({'responsibilities': ['采购审批系统开发']}, candidate,
                            [{'source_id': 't', 'chunk': 8, 'semantic_score': .75, 'text': '项目 ' + source_quote}])
    assert score['dimensions']['projects']['score'] == 75
    assert score['project_evidence'][0]['source_quote'] == source_quote
    assert score['project_evidence'][0]['quote'] == '项目 ' + source_quote


def test_missing_work_history_is_unknown_instead_of_verified_zero_tenure():
    score = score_candidate({'min_experience_months': 48}, {'source': 'manual', 'verified_by': 'hr', 'experiences': []}, [])
    assert next(item for item in score['conditions'] if item['name'] == 'experience')['status'] == 'unknown'
    assert score['eligible'] is False
