"""Equivalent local-model JSON layouts retain the same strict grounding gate."""
from talent_platform.ai import Extraction
from talent_platform.ai_domain import ground_profile, missing_core_fields


def test_top_level_grouped_evidence_is_canonicalized_before_grounding():
    education = {"institution": "合成大学", "degree": "本科"}
    output = {"profile": {"name": "合成甲", "email": "synthetic@example.test",
                          "skills": ["Python", "SQL"], "education": [education]},
              "evidence": [{"field": "name", "value": "合成甲", "quote": "姓名：合成甲"},
                           {"field": "email", "value": "synthetic@example.test", "quote": "synthetic@example.test"},
                           {"field": "skills", "value": ["Python", "SQL"], "quote": "技能：Python、SQL"},
                           {"field": "education", "value": [education], "quote": "合成大学，本科"}]}
    source = "姓名：合成甲\nsynthetic@example.test\n技能：Python、SQL\n合成大学，本科"
    parsed = Extraction.model_validate(output).profile
    profile, _ = ground_profile(parsed, source)
    assert missing_core_fields(profile) == []
    assert profile["skills"] == ["Python", "SQL"]
    assert profile["education"] == [education]
    assert output["evidence"][2]["value"] == ["Python", "SQL"]  # no mutation of model result


def test_equivalent_evidence_layout_never_bypasses_quote_or_value_validation():
    output = {"profile": {"name": "幻觉姓名", "skills": ["Python", "Java"]},
              "evidence": [{"field": "name", "value": "幻觉姓名", "quote": "不存在的原文"},
                           {"field": "skills", "value": ["Python", "Java"], "quote": "技能：Python"}]}
    profile, _ = ground_profile(Extraction.model_validate(output).profile, "技能：Python")
    assert profile["name"] is None
    assert profile["skills"] == ["Python"]


def test_inline_skill_quotes_are_normalized_but_fabricated_values_still_rejected():
    output = {'profile': {'skills': [{'value': 'Python', 'quote': '技能：Python'},
                                     {'value': 'Java', 'quote': '技能：Python'}], 'evidence': []}}
    parsed = Extraction.model_validate(output).profile
    profile, _ = ground_profile(parsed, '技能：Python')
    assert profile['skills'] == ['Python']
    assert output['profile']['skills'][0]['value'] == 'Python'


def test_evidence_only_output_provides_candidates_but_still_requires_source_binding():
    output = {'profile': {'evidence': [
        {'field': 'name', 'value': '合成甲', 'quote': '姓名：合成甲'},
        {'field': 'skills', 'value': ['Python', 'Java'], 'quote': '技能：Python'},
        {'field': 'email', 'value': 'invented@example.test', 'quote': '未出现邮箱'},
        {'field': 'education', 'value': {'school': '合成大学'}, 'quote': '合成大学'}]}}
    raw = Extraction.model_validate(output).profile
    profile, _ = ground_profile(raw, '姓名：合成甲\n技能：Python\n合成大学')
    assert profile['name'] == '合成甲' and profile['skills'] == ['Python']
    assert profile['education'] == [{'school': '合成大学'}]
    assert profile['email'] is None


def test_evidence_candidates_never_overwrite_explicit_identity_field():
    output = {'profile': {'name': '合成甲', 'evidence': [
        {'field': 'name', 'value': '合成乙', 'quote': '合成乙'}]}}
    raw = Extraction.model_validate(output).profile
    assert raw['name'] == '合成甲'
    assert ground_profile(raw, '合成乙')[0]['name'] is None


def test_evidence_field_names_are_case_insensitive_without_translating_values():
    output = {'profile': {'evidence': [
        {'field': 'Name', 'value': 'Synthetic Candidate', 'quote': 'Name: Synthetic Candidate'},
        {'field': 'Skills', 'value': ['Python'], 'quote': 'Skills: Python'}]}}
    profile, _ = ground_profile(Extraction.model_validate(output).profile, 'Name: Synthetic Candidate\nSkills: Python')
    assert profile['name'] == 'Synthetic Candidate' and profile['skills'] == ['Python']
