import pytest
from talent.domain import derive_portrait, education_rank, score_candidate, validate_evidence
from talent.repository import union_profiles
from talent.schemas import Evidence, Experience, JobRequirements, TalentProfile


@pytest.mark.parametrize('field,value,text', [
    ('skills', 'Python', '不具备Python经验'),
    ('certificates', 'PMP', '未取得PMP认证'),
    ('education', '硕士', '未取得硕士学位'),
])
@pytest.mark.parametrize('short_quote', [False, True])
def test_negative_source_is_not_positive_qualification(field, value, text, short_quote):
    payload = [{"degree": value}] if field == 'education' else [value]
    profile = TalentProfile(**{field: payload}, evidence={field: [Evidence(quote=value if short_quote else text)]})
    result = validate_evidence(profile, text)
    assert not getattr(result, field)
    assert result.anomalies


@pytest.mark.parametrize('degree', ['本科肄业', '硕士在读', '未取得博士学位', 'Bachelor incomplete'])
def test_unearned_degree_does_not_satisfy_attained_education(degree):
    assert education_rank(degree) == 0


def test_conflicting_scalar_evidence_is_kept_separately_from_current_value():
    left = TalentProfile(location='北京', evidence={'location': [Evidence(quote='北京', source_id='a')]})
    right = TalentProfile(location='上海', evidence={'location': [Evidence(quote='上海', source_id='b')]})
    result = union_profiles(left, right)
    assert result.location == '北京'
    assert [e.quote for e in result.evidence['location']] == ['北京']
    assert result.evidence['conflicts.location'][0].source_id == 'b'
    assert result.anomalies


@pytest.mark.parametrize('title,description,skill,want', [
    ('Python工程师', '', 'Python', 100),
    (None, 'JavaScript developer', 'Java', 0),
])
def test_relevant_experience_uses_verified_title_and_whole_skill_tokens(title, description, skill, want):
    profile = derive_portrait(TalentProfile(skills=[skill], experiences=[
        Experience(title=title, description=description, start='2020-01', end='2024-01')]))
    score = score_candidate(profile, JobRequirements(required_skills=[skill], min_experience_months=36))
    assert next(d.score for d in score.dimensions if d.key == 'experience') == want
