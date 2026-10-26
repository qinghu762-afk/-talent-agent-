
import pytest
from talent.adapters import PrivateModels, build_filter, validate_job_evidence, vector_chunks
from talent.schemas import Evidence, JobRequirements, Project, ResumeExtraction, TalentProfile


def test_filter_escapes_arbitrary_location_as_literal():
    expr = build_filter(JobRequirements(location='北京" or active == true or "'))
    assert '\\"' in expr
    assert expr.startswith("active == true")


def test_preferred_skills_never_become_hard_requirements():
    req = JobRequirements(required_skills=["Python"], evidence={"required_skills": [Evidence(quote="Python优先")]})
    clean = validate_job_evidence(req, "Python优先")
    assert clean.required_skills == []
    assert clean.preferred_skills == ["Python"]


def test_hallucinated_job_constraints_removed():
    req = JobRequirements(location="上海", min_experience_months=60, required_skills=["Java"])
    clean = validate_job_evidence(req, "Python工程师")
    assert clean.location is None
    assert clean.min_experience_months is None
    assert clean.required_skills == []


def test_experience_requirement_is_derived_from_source_not_llm_number():
    req = JobRequirements(min_experience_months=120, evidence={
        "min_experience_months": [Evidence(quote="至少3年工作经验")]})
    assert validate_job_evidence(req, "至少3年工作经验").min_experience_months == 36


def test_project_vectors_keep_kind_and_evidence():
    chunks = vector_chunks(TalentProfile(name="张三", projects=[Project(name="支付", description="负责结算")]))
    assert any(c["kind"] == "project" and "结算" in c["text"] for c in chunks)
    assert all(len(c["text"]) <= 3000 for c in chunks)


def test_mixed_must_and_preferred_clauses_keep_the_hard_skill():
    quote = "必须熟悉Java，了解Python者优先"
    req = JobRequirements(required_skills=["Java"], preferred_skills=["Python"], evidence={
        "required_skills": [Evidence(quote=quote)], "preferred_skills": [Evidence(quote=quote)]})
    result = validate_job_evidence(req, quote)
    assert result.required_skills == ["Java"]
    assert result.preferred_skills == ["Python"]


def test_job_evidence_uses_verified_text_position_instead_of_model_page():
    req = JobRequirements(location="北京", evidence={"location": [Evidence(quote="北京", page=999, start=999)]})
    result = validate_job_evidence(req, "地点：北京")
    assert result.evidence["location"][0].page is None
    entry = result.evidence["location"][0]
    # A verified quote may expand to its labeled clause; offset must cite that exact span.
    assert "地点：北京"[entry.start:entry.start + len(entry.quote)] == entry.quote


@pytest.mark.parametrize("quote,want", [("3-5年工作经验", 36), ("三年以上工作经验", 36),
                                                   ("至少3年6个月工作经验", 42), ("至少3年经验，Python优先", 36)])
def test_experience_ranges_and_chinese_numbers_preserve_minimum(quote, want):
    req = JobRequirements(min_experience_months=99, evidence={"min_experience_months": [Evidence(quote=quote)]})
    assert validate_job_evidence(req, quote).min_experience_months == want


def test_empty_extraction_cannot_be_reported_as_success(monkeypatch):
    models = object.__new__(PrivateModels)
    empty = ResumeExtraction(name=None, phone=None, email=None, location=None, education=[], experiences=[],
                             projects=[], skills=[], certificates=[], intentions=[], evidence=[])
    monkeypatch.setattr(models, "extract", lambda *args: empty)
    with pytest.raises(ValueError, match="人才信息"):
        models.resume("无法识别的人才文件")


def test_local_model_path_typo_and_corrupted_date_are_corrected_only_from_original_quote(monkeypatch):
    raw = ResumeExtraction(name=None, phone=None, email=None, location=None, education=[],
        experiences=[{"company": None, "title": None, "start": "2020年1月", "end": "2:023年1月", "description": "", "skills": []}],
        projects=[], skills=["Python"], certificates=[], intentions=[], evidence=[
            {"field": "skills.0", "quote": "Python"}, {"field": "experience.0.start", "quote": "2020年1月"},
            {"field": "experience.0.end", "quote": "2023年1月"}])
    models = object.__new__(PrivateModels)
    monkeypatch.setattr(models, "extract", lambda *args: raw)
    profile = models.resume("Python 2020年1月到2023年1月")
    assert profile.experience_months == 36
    assert profile.experiences[0].end == "2023-01"
    assert profile.evidence["experiences.0.end"][0].quote == "2023年1月"


def test_job_location_and_experience_are_not_scored_as_project_duties():
    text = "工作地点：北京。至少三年工作经验。负责开发支付平台。"
    req = JobRequirements(responsibilities=["工作地点：北京", "至少三年工作经验", "负责开发支付平台"], evidence={
        "responsibilities": [Evidence(quote="工作地点：北京"), Evidence(quote="至少三年工作经验"),
                             Evidence(quote="负责开发支付平台")]})
    assert validate_job_evidence(req, text).responsibilities == ["负责开发支付平台"]


def test_flat_local_model_evidence_paths_preserve_uniquely_grounded_facts(monkeypatch):
    raw = ResumeExtraction(name="合成甲", phone=None, email=None, location=None, education=[],
        experiences=[{"company": "合成公司", "title": "Python工程师", "start": "2020-01", "end": "2024-01", "description": "", "skills": []}],
        projects=[], skills=[], certificates=["PMP"], intentions=[], evidence=[
            {"field": "name", "quote": "合成甲"}, {"field": "company", "quote": "合成公司"},
            {"field": "title", "quote": "Python工程师"}, {"field": "start", "quote": "2020-01"},
            {"field": "end", "quote": "2024-01"}, {"field": "certificate", "quote": "PMP"}])
    models = object.__new__(PrivateModels)
    monkeypatch.setattr(models, "extract", lambda *args: raw)
    profile = models.resume("合成甲 合成公司 Python工程师 2020-01至2024-01 证书PMP")
    assert profile.experience_months == 48
    assert profile.certificates == ["PMP"]
    assert profile.evidence["experiences.0.start"][0].quote == "2020-01"


def test_flat_evidence_does_not_guess_between_multiple_employments(monkeypatch):
    raw = ResumeExtraction(name="合成甲", phone=None, email=None, location=None, education=[],
        experiences=[{"company": "同名公司", "title": None, "start": "2020-01", "end": "2021-01", "description": "", "skills": []},
                     {"company": "同名公司", "title": None, "start": "2022-01", "end": "2023-01", "description": "", "skills": []}],
        projects=[], skills=[], certificates=["PMP"], intentions=[], evidence=[
            {"field": "name", "quote": "合成甲"}, {"field": "company", "quote": "同名公司"},
            {"field": "start", "quote": "2020-01"}, {"field": "end", "quote": "2021-01"},
            {"field": "certificate", "quote": "并不存在的PMP证据"}])
    models = object.__new__(PrivateModels)
    monkeypatch.setattr(models, "extract", lambda *args: raw)
    profile = models.resume("合成甲 同名公司 2020-01至2021-01，2022-01至2023-01")
    assert profile.certificates == []
    assert profile.experience_months == 12
    assert all(item.company is None for item in profile.experiences)


def test_corrupted_contact_value_is_repaired_only_from_one_exact_verified_contact(monkeypatch):
    raw = ResumeExtraction(name=None, phone=None, email="candidate02:28@example.invalid", location=None,
        education=[], experiences=[], projects=[], skills=[], certificates=[], intentions=[],
        evidence=[{"field": "email", "quote": "candidate028@example.invalid"}])
    models = object.__new__(PrivateModels)
    monkeypatch.setattr(models, "extract", lambda *args: raw)
    assert models.resume("Email: candidate028@example.invalid").email == "candidate028@example.invalid"


def test_contact_repair_cannot_choose_conflicting_quotes_or_fill_absent_values():
    from talent.domain import validate_evidence

    text = "a@example.invalid b@example.invalid"
    evidence = {"email": [Evidence(quote="a@example.invalid"), Evidence(quote="b@example.invalid")]}
    assert validate_evidence(TalentProfile(email="broken", evidence=evidence), text).email is None
    assert validate_evidence(TalentProfile(email=None, evidence={"email": [Evidence(quote="a@example.invalid")]}), text).email is None


@pytest.mark.parametrize("text, expected", [("Minimum 24 months experience.", 24),
                                           ("24 months experience preferred.", None)])
def test_numeric_job_quote_uses_unique_adjacent_original_unit_and_preference(text, expected):
    req = JobRequirements(min_experience_months=999, evidence={"min_experience_months": [Evidence(quote="24")]})
    result = validate_job_evidence(req, text)
    assert result.min_experience_months == expected
    if expected is not None:
        assert result.evidence["min_experience_months"][0].quote in text


def test_corrupted_job_quote_can_only_be_repaired_from_uniquely_labeled_original_requirement():
    text = "Required skill: Java. Required location: SHANGHAI."
    req = JobRequirements(required_skills=["Java"], location="SHANGHAI", evidence={
        "required_skills": [Evidence(quote="Java")], "location": [Evidence(quote="SHANG:GHI")]})
    clean = validate_job_evidence(req, text)
    assert clean.location == "SHANGHAI"
    assert clean.evidence["location"][0].quote == "Required location: SHANGHAI"


def test_short_skill_quote_preserves_preferred_context_even_when_title_repeats_skill():
    text = "Python engineer. Python优先。"
    req = JobRequirements(required_skills=["Python"], evidence={"required_skills": [Evidence(quote="Python")]})
    clean = validate_job_evidence(req, text)
    assert clean.required_skills == []
    assert clean.preferred_skills == ["Python"]


@pytest.mark.parametrize("model_location", [None, "SHANG:GHI"])
def test_explicit_labeled_hard_location_cannot_disappear_due_to_model_omission_or_typo(model_location):
    req = JobRequirements(location=model_location)
    clean = validate_job_evidence(req, "Required location: SHANGHAI.")
    assert clean.location == "SHANGHAI"
    assert clean.evidence["location"][0].quote == "Required location: SHANGHAI"


def test_underfilled_milvus_group_search_recovers_distinct_filtered_candidates():
    from talent.adapters import VectorStore

    def hit(name, distance):
        return {"entity": {"talent_id": name, "revision": 1, "kind": "project"}, "distance": distance}

    class CapturedClient:
        def search(self, collection, **kwargs):
            assert 'location == "shanghai"' in kwargs["filter"]
            assert 'talent_id in ["a", "b", "c"]' in kwargs["filter"]
            if kwargs.get("group_by_field"):
                return [[hit("a", .87), hit("b", .87)]]
            return [[hit("a", .87), hit("b", .87), hit("c", .83), hit("a", .77)]]

    store = object.__new__(VectorStore)
    store.client, store.collection = CapturedClient(), "test"
    store.ensure = lambda: None
    hits = store.search([1.0, 0.0], JobRequirements(location="SHANGHAI"), limit=3, ids=["a", "b", "c"])
    assert [h["entity"]["talent_id"] for h in hits] == ["a", "b", "c"]


def test_parenthetical_preference_does_not_remove_mandatory_skill():
    text = "必须掌握Python（PostgreSQL优先）"
    req = JobRequirements(required_skills=["Python"], evidence={"required_skills": [Evidence(quote=text)]})
    assert validate_job_evidence(req, text).required_skills == ["Python"]


def test_misclassified_required_skill_is_promoted_and_omitted_minimum_recovered():
    text = "必须掌握Python；至少三年工作经验"
    req = JobRequirements(preferred_skills=["Python"])
    result = validate_job_evidence(req, text)
    assert result.required_skills == ["Python"]
    assert result.min_experience_months == 36


def test_omitted_explicit_certificate_cannot_silently_remove_hard_condition():
    with pytest.raises(ValueError, match="硬性要求"):
        validate_job_evidence(JobRequirements(), "必须持有PMP证书")


def test_partial_skill_extraction_cannot_hide_another_explicit_required_skill():
    req = JobRequirements(required_skills=["Python"])
    with pytest.raises(ValueError, match="硬性要求"):
        validate_job_evidence(req, "必须掌握Python和Java")


def test_local_embedding_requests_are_bounded_and_preserve_chunk_order():
    from types import SimpleNamespace

    sizes = []
    class Embedding:
        def embed_documents(self, values):
            sizes.append(len(values))
            return [[float(value), 0.0] for value in values]
    models = object.__new__(PrivateModels)
    models.config = SimpleNamespace(embedding_dimension=2)
    models.embedding = Embedding()
    models.versions = lambda: {}
    result = models.embed([str(i) for i in range(65)])
    assert sizes == [32, 32, 1]
    assert result == [[float(i), 0.0] for i in range(65)]

