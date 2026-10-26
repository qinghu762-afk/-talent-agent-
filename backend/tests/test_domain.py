from datetime import date

import pytest
from talent.domain import (
    assess_identity,
    canonical_skill,
    experience_months,
    normalize_contact,
    score_candidate,
    validate_evidence,
)
from talent.schemas import Evidence, Experience, JobRequirements, TalentProfile


def profile(**kw):
    return TalentProfile(**{"name": "张三", "skills": ["Python", "SQL"], **kw})


@pytest.mark.parametrize("raw,want", [("python3", "Python"), ("JS", "JavaScript"), ("Postgres", "PostgreSQL")])
def test_skill_aliases(raw, want):
    assert canonical_skill(raw) == want


def test_contact_normalization():
    assert normalize_contact("+86 138-0013-8000", "phone") == "13800138000"
    assert normalize_contact(" A@EXAMPLE.COM ", "email") == "a@example.com"


def test_overlapping_employment_not_double_counted():
    jobs = [Experience(start="2020-01", end="2022-01"), Experience(start="2021-01", end="2023-01")]
    assert experience_months(jobs, date(2026, 10, 20)) == 36


def test_invalid_or_future_dates_do_not_invent_experience():
    assert experience_months([Experience(start="bad", end="2025-01")], date(2026, 10, 20)) == 0
    assert experience_months([Experience(start="2028-01", end=None)], date(2026, 10, 20)) == 0


def test_same_name_alone_never_merges():
    assert assess_identity(profile(), profile()).decision == "distinct"


def test_same_identity_merges():
    assert assess_identity(profile(phone="13800138000"), profile(phone="+86 13800138000")).decision == "merge"


def test_conflicting_contact_blocks_merge_even_with_one_matching_contact():
    a = profile(phone="13800138000", email="a@example.com")
    b = profile(phone="13800138000", email="b@example.com")
    assert assess_identity(a, b).decision == "conflict"


def test_shared_contact_and_different_name_never_merge():
    assert assess_identity(profile(phone="13800138000"), profile(name="李四", phone="13800138000")).decision != "merge"


def test_hallucinated_and_unproven_fields_are_removed():
    p = profile(phone="13800138000", evidence={
        "name": [Evidence(quote="张三", page=1)],
        "phone": [Evidence(quote="不存在的号码", page=1)],
        "skills": [Evidence(quote="Python", page=1)],
    })
    clean = validate_evidence(p, "张三 熟练 Python")
    assert clean.name == "张三"
    assert clean.phone is None
    assert clean.skills == ["Python"]
    assert clean.anomalies


def test_unknown_mandatory_education_excluded():
    result = score_candidate(profile(), JobRequirements(min_education="本科"), 0.99)
    assert not result.eligible
    assert result.conditions[0].status == "unknown"


def test_required_skill_missing_excluded_even_when_semantically_similar():
    result = score_candidate(profile(), JobRequirements(required_skills=["Java"]), 0.99)
    assert not result.eligible


def test_alias_matching_and_unused_weight_renormalization():
    result = score_candidate(profile(skills=["python3"]), JobRequirements(required_skills=["Python"]), 0)
    assert result.eligible
    assert result.total == 100
    assert result.dimensions[0].weight == 1


def test_no_requirements_is_not_a_perfect_match():
    result = score_candidate(profile(), JobRequirements(), 1)
    assert result.total == 0
    assert result.unknowns


def test_unproven_project_similarity_does_not_award_project_points():
    result = score_candidate(profile(projects=[]), JobRequirements(responsibilities=["支付系统"]), 1)
    assert result.total == 0


def test_hard_certificate_and_location_are_enforced():
    result = score_candidate(profile(location="北京"), JobRequirements(location="上海", required_certificates=["PMP"]), 1)
    assert not result.eligible
    assert len(result.conditions) == 2


def test_date_formats_normalize_without_losing_grounding():
    p = profile(experiences=[Experience(start="2020年1月", end="2022/01")], evidence={
        "experiences.0.start": [Evidence(quote="2020年1月")],
        "experiences.0.end": [Evidence(quote="2022/01")],
    })
    clean = validate_evidence(p, "工作经历 2020年1月 — 2022/01")
    assert clean.experiences[0].start == "2020-01"
    assert clean.experiences[0].end == "2022-01"
    assert clean.experience_months == 24


def test_unverified_model_page_number_is_not_presented_as_fact():
    p = profile(evidence={"name": [Evidence(quote="张三", page=999)]})
    clean = validate_evidence(p, "姓名：张三")
    assert clean.evidence["name"][0].page is None
    assert clean.evidence["name"][0].start == 3


@pytest.mark.parametrize("claimed,actual", [("Java", "JavaScript"), ("Go", "Google")])
def test_substring_is_not_proof_of_a_different_skill(claimed, actual):
    clean = validate_evidence(profile(skills=[claimed], evidence={"skills.0": [Evidence(quote=actual)]}), actual)
    assert clean.skills == []


def test_normalization_rebuilds_evidence_paths_after_sort_and_filter():
    clean = validate_evidence(profile(skills=["Redis", "invented", "python3"], evidence={
        "skills.0": [Evidence(quote="Redis")], "skills.2": [Evidence(quote="python3")],
    }), "Redis python3")
    assert clean.skills == ["Python", "Redis"]
    assert clean.evidence["skills.0"][0].quote == "python3"
    assert clean.evidence["skills.1"][0].quote == "Redis"


def test_translated_ongoing_date_keeps_source_evidence():
    p = profile(experiences=[Experience(start="2020-01", end="Present")], evidence={
        "experiences.0.start": [Evidence(quote="2020-01")], "experiences.0.end": [Evidence(quote="Present")],
    })
    clean = validate_evidence(p, "2020-01 to Present")
    assert clean.experiences[0].end == "至今"
    assert clean.evidence["experiences.0.end"][0].quote == "Present"

