from talent_platform.prompts import model_prompt


def test_resume_prompt_separates_untrusted_text_from_output_and_omits_internal_state():
    request = {"task": "resume", "text": "姓名：合成甲\n技能：Python", "round": 2, "chunk": 0,
               "schema": {"profile": {"name": None, "skills": [], "evidence": []}},
               "verified_profile": {"name": "合成甲", "derived_fields": {"internal": True}},
               "missing_fields": ["contact"], "validation_issues": ["invalid_structured_output"]}
    prompt = model_prompt(request)
    assert "姓名：合成甲" in prompt and '"profile"' in prompt
    assert "derived_fields" not in prompt and '"task"' not in prompt
    assert "contact" in prompt and "invalid_structured_output" in prompt
    assert prompt.rindex("姓名：合成甲") > prompt.index('"profile"')
    assert '"value": "原文值"' not in prompt


def test_non_resume_task_keeps_authorized_context_and_exact_return_template():
    prompt = model_prompt({"task": "chat", "question": "制度是什么", "context": [{"source_id": "doc", "text": "合成制度"}], "schema": {"answer": "", "citations": []}})
    assert "合成制度" in prompt and "citations" in prompt and "不可信" in prompt
    assert prompt.rindex('合成制度') > prompt.index('"citations"')
    assert '每个事实必须绑定evidence' not in prompt
    assert '"answer": ""' not in prompt


def test_job_prompt_demands_per_requirement_evidence_and_preserves_priority():
    prompt = model_prompt({'task': 'job', 'description': '必须Python，SQL优先', 'schema': {'requirements': {'required_skills': [], 'preferred_skills': [], 'evidence': []}}})
    assert 'field=required_skills' in prompt and 'field=preferred_skills' in prompt
    assert prompt.rindex('必须Python，SQL优先') > prompt.index('"requirements"')
