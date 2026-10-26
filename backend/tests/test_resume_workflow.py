"""Exercise the real graph and validators; substitute only model responses."""
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from langchain_core.exceptions import OutputParserException
from talent.adapters import PrivateModels
from talent.schemas import ResumeExtraction

TEXT = "姓名：合成甲\n电话：13800138000\n邮箱：cv@example.invalid\n技能：Python SQL\n学校：合成大学\n学历：本科\n公司：合成公司\n职位：Python工程师"


def raw(**updates):
    data = dict(name=None, phone=None, email=None, location=None, education=[], experiences=[],
                projects=[], skills=[], certificates=[], intentions=[], evidence=[])
    data.update(updates)
    return ResumeExtraction(**data)


def complete(**updates):
    data = dict(name="合成甲", phone="13800138000", skills=["Python"],
                education=[dict(school="合成大学", degree="本科", major=None)], evidence=[
                    dict(field="name", quote="合成甲"), dict(field="phone", quote="13800138000"),
                    dict(field="skills.0", quote="Python"), dict(field="education.0.school", quote="合成大学"),
                    dict(field="education.0.degree", quote="本科")])
    data.update(updates)
    return raw(**data)


def scripted(monkeypatch, responses):
    models = object.__new__(PrivateModels)
    calls = []
    iterator = iter(responses)

    def extract(schema, text, purpose):
        calls.append((text, purpose))
        response = next(iterator)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(models, "extract", extract)
    return models, calls


def test_complete_first_pass_skips_repair(monkeypatch):
    models, calls = scripted(monkeypatch, [complete()])
    result = models.resume_with_report(TEXT)
    assert result.report.quality_status == "complete"
    assert result.report.retry_count == 0
    assert result.report.missing_fields == []
    assert result.report.stop_reason == "complete"
    assert result.profile.completeness < 100  # Core gate is independent of the eight-field metric.
    assert len(calls) == 1


@pytest.mark.parametrize("contact", ["phone", "email"])
@pytest.mark.parametrize("history", ["education", "experiences"])
def test_either_contact_and_graduate_or_employee_can_be_complete(monkeypatch, contact, history):
    data = complete().model_dump()
    data["phone"] = None
    data[contact] = "13800138000" if contact == "phone" else "cv@example.invalid"
    data["evidence"].append(dict(field=contact, quote=data[contact]))
    if history == "experiences":
        data["education"] = []
        data["experiences"] = [dict(company="合成公司", title="Python工程师", start=None, end=None, description="", skills=[])]
        data["evidence"] += [dict(field="experiences.0.company", quote="合成公司"), dict(field="experiences.0.title", quote="Python工程师")]
    models, calls = scripted(monkeypatch, [raw(**data)])
    assert models.resume_with_report(TEXT).report.quality_status == "complete"
    assert len(calls) == 1


def test_missing_contact_is_repaired_without_overwriting_verified_name(monkeypatch):
    first = complete(phone=None)
    repair = raw(name="合成乙", email="cv@example.invalid", evidence=[
        dict(field="name", quote="合成乙"), dict(field="email", quote="cv@example.invalid")])
    models, calls = scripted(monkeypatch, [first, repair])
    result = models.resume_with_report(TEXT + "\n推荐人：合成乙")
    assert result.profile.name == "合成甲"
    assert result.profile.email == "cv@example.invalid"
    assert result.report.quality_status == "complete"
    assert result.report.retry_count == 1
    assert any("name" in issue for issue in result.profile.anomalies)
    assert "contact" in calls[1][1] and "缺失" in calls[1][1]
    assert "13800138000" not in result.report.model_dump_json()
    assert "cv@example.invalid" not in result.report.model_dump_json()


def test_source_missing_returns_partial_and_stops_on_no_progress(monkeypatch):
    first = raw(skills=["Python"], evidence=[dict(field="skills.0", quote="Python")])
    models, calls = scripted(monkeypatch, [first, first])
    result = models.resume_with_report("技能：Python")
    assert result.report.quality_status == "partial"
    assert result.report.stop_reason == "no_progress"
    assert result.report.retry_count == 1
    assert result.report.missing_fields == ["name", "contact", "education_or_experiences"]
    assert result.profile.name is None and result.profile.phone is None
    assert any("核心信息" in issue for issue in result.profile.anomalies)
    assert len(calls) == 2


def test_three_document_repair_rounds_are_the_maximum_even_with_progress(monkeypatch):
    models, calls = scripted(monkeypatch, [raw(), raw(name="合成甲", evidence=[dict(field="name", quote="合成甲")]),
        raw(phone="13800138000", evidence=[dict(field="phone", quote="13800138000")]),
        raw(skills=["Python"], evidence=[dict(field="skills.0", quote="Python")])])
    result = models.resume_with_report(TEXT)
    assert result.report.retry_count == 3
    assert result.report.stop_reason == "retry_limit"
    assert result.report.missing_fields == ["education_or_experiences"]
    assert len(calls) == 4


def test_invalid_structured_response_can_recover_and_feedback_is_redacted(monkeypatch):
    models, calls = scripted(monkeypatch, [OutputParserException("secret cv@example.invalid"), complete()])
    result = models.resume_with_report(TEXT)
    assert result.report.quality_status == "complete" and result.report.retry_count == 1
    assert "OutputParserException" in calls[1][1]
    assert "secret" not in calls[1][1]
    assert "cv@example.invalid" not in result.report.model_dump_json()


def test_exhausted_invalid_output_is_permanent_business_failure(monkeypatch):
    models, calls = scripted(monkeypatch, [OutputParserException("private text")] * 4)
    with pytest.raises(ValueError, match="人才信息") as caught:
        models.resume_with_report(TEXT)
    assert not isinstance(caught.value, OutputParserException)
    assert "private text" not in str(caught.value)
    assert len(calls) == 4


def test_partial_facts_survive_three_invalid_repairs(monkeypatch):
    models, calls = scripted(monkeypatch, [complete(phone=None)] + [OutputParserException("private")] * 3)
    result = models.resume_with_report(TEXT)
    assert result.profile.name == "合成甲" and result.profile.phone is None
    assert result.report.quality_status == "partial" and result.report.retry_count == 3
    assert len(calls) == 4


@pytest.mark.parametrize("text", ["", " \n\t"])
def test_empty_input_fails_without_calling_model(monkeypatch, text):
    models, calls = scripted(monkeypatch, [])
    with pytest.raises(ValueError, match="文字"):
        models.resume_with_report(text)
    assert calls == []


def test_network_failure_is_left_to_durable_task_retry(monkeypatch):
    models, calls = scripted(monkeypatch, [httpx.ReadTimeout("private network message")])
    with pytest.raises(httpx.ReadTimeout):
        models.resume_with_report(TEXT)
    assert len(calls) == 1


def test_long_document_is_checked_after_all_chunks_not_per_chunk(monkeypatch):
    text = TEXT[:TEXT.index("学校")] + "\n" * 4000 + TEXT[TEXT.index("学校"):]
    first = complete(education=[])
    second = raw(education=[dict(school="合成大学", degree=None, major=None)],
                 evidence=[dict(field="education.0.school", quote="合成大学")])
    models, calls = scripted(monkeypatch, [first, second])
    result = models.resume_with_report(text)
    assert result.report.retry_count == 0 and result.report.quality_status == "complete"
    assert len(calls) == 2


def test_hallucinations_and_unrequested_lists_do_not_increase_progress(monkeypatch):
    first = complete(phone=None)
    repair = raw(phone="13900139000", projects=[dict(name="虚构项目", description="", skills=[])],
                 skills=["SQL"], evidence=[dict(field="phone", quote="不存在的电话"), dict(field="skills.0", quote="SQL")])
    models, calls = scripted(monkeypatch, [first, repair])
    result = models.resume_with_report(TEXT)
    assert result.profile.phone is None and result.profile.projects == []
    assert result.profile.skills == ["Python"]
    assert result.report.stop_reason == "no_progress" and len(calls) == 2


def test_graph_state_is_isolated_between_concurrent_calls(monkeypatch):
    models = object.__new__(PrivateModels)
    monkeypatch.setattr(models, "extract", lambda *args: complete())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(models.resume_with_report, [TEXT] * 4))
    results[0].report.missing_fields.append("changed")
    results[0].profile.skills.append("changed")
    assert all(r.report.missing_fields == [] and r.profile.skills == ["Python"] for r in results[1:])
    assert "13800138000" not in json.dumps([r.report.model_dump() for r in results])


@pytest.mark.parametrize("quote,source,expected", [
    ("技能：Python、SQL。", "技能：Python、SQL。", ["Python", "SQL"]),
    ("Python。", "掌握 Python。", ["Python"]),
    ("Python。", "不会 Python。", []),
])
def test_source_clause_punctuation_does_not_invalidate_real_evidence(monkeypatch, quote, source, expected):
    response = raw(name="合成甲", skills=["Python", "SQL"], evidence=[dict(field="name", quote="合成甲"), dict(field="skills", quote=quote)])
    models = object.__new__(PrivateModels)
    monkeypatch.setattr(models, "extract", lambda *args: response)
    result = models.resume_with_report("姓名：合成甲\n" + source)
    assert result.profile.skills == expected


def test_failed_chunk_is_reextracted_in_full_even_when_other_chunk_has_core_fields(monkeypatch):
    text = TEXT + "\n" * 4000 + "项目：结算系统\n负责支付结算开发"
    project = raw(projects=[dict(name="结算系统", description="负责支付结算开发", skills=[])], evidence=[
        dict(field="projects.0.name", quote="结算系统"), dict(field="projects.0.description", quote="负责支付结算开发")])
    models, calls = scripted(monkeypatch, [complete(), OutputParserException("bad chunk")] + [project] * 4)
    result = models.resume_with_report(text)
    assert [p.name for p in result.profile.projects] == ["结算系统"]
    assert result.report.quality_status == "complete" and result.report.retry_count == 1
    assert len(calls) == 3  # Only the failed chunk needs full replay.
