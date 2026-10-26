"""The graph report and its verified facts must share the ingestion commit."""
import pytest
from sqlalchemy import select
from talent.adapters import PrivateModels
from talent.db import Document, Issue, Talent, Work, session
from talent.pipeline import Pipeline, execute_work
from talent.schemas import TalentProfile
from test_api import login
from test_pipeline import Parser, Vectors
from test_resume_workflow import TEXT, complete, raw

pytest_plugins = ["test_api"]


def model(monkeypatch, response):
    models = object.__new__(PrivateModels)
    monkeypatch.setattr(models, "extract", lambda *args: response)
    monkeypatch.setattr(models, "versions", lambda: {
        "chat": {"name": "test", "digest": "chat1"}, "embedding": {"name": "test", "digest": "embed1"}})
    monkeypatch.setattr(models, "embed", lambda texts: [[1.0, 0.0] for _ in texts])
    return models


def test_partial_report_persisted_and_hash_reuse_does_not_rerun_graph(client, monkeypatch):
    login(client)
    models = model(monkeypatch, raw(skills=["Python"], evidence=[dict(field="skills.0", quote="Python")]))
    parser = Parser()
    monkeypatch.setattr(parser, "parse", lambda document: ("技能：Python", "test-parser"))
    client.post("/api/v1/batches", files={"files": ("partial.txt", b"unique partial source")})
    with session() as db:
        work_id = db.scalar(select(Work.id).where(Work.kind == "ingest"))
    pipeline = Pipeline(models, parser, lambda digest: Vectors())
    execute_work(work_id, pipeline)
    with session() as db:
        document = db.scalar(select(Document))
        assert document.model_versions["resume_workflow"]["quality_status"] == "partial"
        assert document.model_versions["resume_workflow"]["retry_count"] == 1
        assert document.model_versions["parser"] == "test-parser"
        assert document.model_versions["chat"]["digest"] == "chat1"
        assert db.get(Work, work_id).status == "completed"
        assert db.get(Work, work_id).attempts == 1
        talent_id = document.talent_id
        assert any("核心信息" in issue.detail for issue in db.scalars(select(Issue)))
        index_id = db.scalar(select(Work.id).where(Work.kind == "index"))
    execute_work(index_id, pipeline)
    detail = client.get("/api/v1/talents/" + talent_id).json()
    assert detail["revision"] == detail["indexed_revision"]
    assert detail["documents"][0]["model_versions"]["resume_workflow"]["stop_reason"] == "no_progress"
    monkeypatch.setattr(models, "resume_with_report", lambda *args: pytest.fail("Cached extraction reran"))
    reused = client.post("/api/v1/batches", files={"files": ("same.txt", b"unique partial source")}).json()
    assert reused["items"][0]["reused"]
    with session() as db:
        assert len(db.scalars(select(Talent)).all()) == 1


def test_historical_extraction_cache_without_report_remains_usable(client, monkeypatch):
    login(client)
    models = model(monkeypatch, complete())
    client.post("/api/v1/batches", files={"files": ("cached.txt", b"old extraction source")})
    with session() as db:
        document = db.scalar(select(Document))
        document.text = TEXT
        document.extracted = TalentProfile(name="合成甲").model_dump()
        document.model_versions = {"parser": "legacy"}
        work_id = db.scalar(select(Work.id).where(Work.kind == "ingest"))
    monkeypatch.setattr(models, "resume_with_report", lambda *args: pytest.fail("Historical cache reran"))
    execute_work(work_id, Pipeline(models, Parser(), lambda digest: Vectors()))
    with session() as db:
        document = db.scalar(select(Document))
        assert document.talent_id
        assert document.model_versions == {"parser": "legacy"}
        assert db.get(Work, work_id).status == "completed"


def test_two_new_versions_merge_without_losing_per_document_report(client, monkeypatch):
    login(client)
    models = model(monkeypatch, complete())
    parser = Parser()
    monkeypatch.setattr(parser, "parse", lambda document: (TEXT, "test-parser"))
    pipeline = Pipeline(models, parser, lambda digest: Vectors())
    for payload in (b"version one", b"version two"):
        client.post("/api/v1/batches", files={"files": ("version.txt", payload)})
        with session() as db:
            work_id = db.scalar(select(Work.id).where(Work.kind == "ingest", Work.status == "queued"))
        execute_work(work_id, pipeline)
    with session() as db:
        documents = db.scalars(select(Document)).all()
        assert len({d.talent_id for d in documents}) == 1 and documents[0].talent_id
        assert all(d.model_versions["resume_workflow"]["quality_status"] == "complete" for d in documents)
        assert len(db.scalars(select(Talent)).all()) == 1
