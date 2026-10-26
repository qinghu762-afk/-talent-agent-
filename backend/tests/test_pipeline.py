from datetime import timedelta

import pytest
from sqlalchemy import select
from talent.db import Job, MatchRun, Talent, Work, session, utcnow
from talent.pipeline import Pipeline, dispatch_pending, execute_work
from talent.repository import enqueue
from talent.resume_workflow import ResumeWorkflowReport, ResumeWorkflowResult
from talent.schemas import JobRequirements, TalentProfile
from test_api import login

pytest_plugins = ["test_api"]


class Models:
    def versions(self):
        return {"chat": {"name": "test", "digest": "chat1"}, "embedding": {"name": "test", "digest": "embed1"}}

    def resume(self, text):
        return TalentProfile(name="张三", phone="13800138000", skills=["Python"])

    def resume_with_report(self, text):
        return ResumeWorkflowResult(profile=self.resume(text), report=ResumeWorkflowReport(
            quality_status="partial", missing_fields=["education_or_experiences"], retry_count=1,
            stop_reason="no_progress", trace=[]))

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def job(self, text):
        return JobRequirements(required_skills=["Python"])


class Parser:
    def parse(self, document):
        return "张三 Python 13800138000", "test-parser"


class Vectors:
    fail = False
    hits = []

    def replace(self, talent, chunks, vectors):
        if self.fail:
            raise ConnectionError("secret phone 13800138000 must never leak")

    def search(self, vector, requirements=None, limit=100, **kw):
        return self.hits


def pipeline(vectors=None):
    return Pipeline(Models(), Parser(), lambda digest: vectors or Vectors())


def test_ingestion_redelivery_and_index_failure_keep_profile(client):
    login(client)
    client.post("/api/v1/batches", files={"files": ("resume.txt", b"hello")})
    with session() as db:
        work_id = db.scalar(select(Work.id).where(Work.kind == "ingest"))
    execute_work(work_id, pipeline())
    execute_work(work_id, pipeline())
    with session() as db:
        assert len(db.scalars(select(Talent)).all()) == 1
        index_id = db.scalar(select(Work.id).where(Work.kind == "index"))
    vectors = Vectors()
    vectors.fail = True
    execute_work(index_id, pipeline(vectors))
    with session() as db:
        w = db.get(Work, index_id)
        assert w.status == "retry"
        assert "13800138000" not in w.error
        assert db.scalar(select(Talent)).indexed_revision == 0
        w.available_at = utcnow()
    vectors.fail = False
    execute_work(index_id, pipeline(vectors))
    with session() as db:
        assert db.get(Work, index_id).status == "completed"
        assert db.scalar(select(Talent)).indexed_revision == 1


def test_stale_index_hits_never_enter_matching_results(client):
    with session() as db:
        p = TalentProfile(name="张三", skills=["Python"])
        talent = Talent(name=p.name, profile=p.model_dump(), revision=2, indexed_revision=2, index_model="embed1")
        job = Job(title="开发", description="Python", status="completed", requirements={"required_skills": ["Python"]})
        db.add_all([talent, job])
        db.flush()
        run = MatchRun(job_id=job.id, job_snapshot={"requirements": job.requirements})
        db.add(run)
        db.flush()
        work = enqueue(db, "match", {"run_id": run.id})
        work_id, run_id, talent_id = work.id, run.id, talent.id
    vectors = Vectors()
    vectors.hits = [{"entity": {"talent_id": talent_id, "revision": 1, "kind": "summary"}, "distance": .99}]
    execute_work(work_id, pipeline(vectors))
    with session() as db:
        assert db.get(MatchRun, run_id).results == []
        assert db.get(MatchRun, run_id).diagnostics["stale_excluded"] == 1


def test_lost_broker_message_is_redispatched_without_losing_task(client):
    with session() as db:
        work = enqueue(db, "index", {"talent_id": "missing", "revision": 1})
        work.status = "dispatched"
        work.updated_at = utcnow() - timedelta(minutes=5)
        work_id = work.id
    delivered = []
    dispatch_pending(lambda task_id, kind: delivered.append(task_id))
    assert work_id in delivered


def test_transient_errors_stop_after_three_retries(client):
    with session() as db:
        work = enqueue(db, "ingest", {"document_id": "missing"})
        task_id = work.id
    class Broken:
        def run(self, kind, payload):
            raise ConnectionError("offline")
    for _ in range(6):
        execute_work(task_id, Broken())
        with session() as db:
            db.get(Work, task_id).available_at = utcnow()
    with session() as db:
        work = db.get(Work, task_id)
        assert work.attempts == 4
        assert work.status == "failed"


@pytest.mark.parametrize("failure", ["schema", "parser", "rate_limit"])
def test_invalid_model_outputs_and_rate_limits_retry_without_disclosing_input(client, failure):
    import httpx
    from langchain_core.exceptions import OutputParserException

    with session() as db:
        job = Job(title="合成岗位", description="Python")
        db.add(job)
        db.flush()
        work = enqueue(db, "job", {"job_id": job.id, "revision": 1})
        work_id = work.id

    class InvalidResponse:
        def run(self, kind, payload):
            if failure == "schema":
                JobRequirements.model_validate({"min_experience_months": "private-13800138000"})
            if failure == "parser":
                raise OutputParserException("private-13800138000")
            response = httpx.Response(429, request=httpx.Request("POST", "http://ollama/api/chat"))
            response.raise_for_status()

    execute_work(work_id, InvalidResponse())
    with session() as db:
        work = db.get(Work, work_id)
        assert work.status == "retry"
        assert work.attempts == 1
        assert "13800138000" not in work.error


def test_orphan_vectors_after_restore_cannot_crowd_out_current_candidates(client):
    with session() as db:
        p = TalentProfile(name="张三", skills=["Python"])
        talent = Talent(name=p.name, profile=p.model_dump(), revision=1, indexed_revision=1, index_model="embed1")
        job = Job(title="开发", description="Python", status="completed", requirements={"required_skills": ["Python"]})
        db.add_all([talent, job])
        db.flush()
        run = MatchRun(job_id=job.id, job_snapshot={"requirements": job.requirements})
        db.add(run)
        db.flush()
        work = enqueue(db, "match", {"run_id": run.id})
        work_id, run_id, talent_id = work.id, run.id, talent.id
    class RestoredStore(Vectors):
        def search(self, vector, requirements=None, limit=100, **kw):
            if kw.get("ids") is not None:
                return [{"entity": {"talent_id": talent_id, "revision": 1, "kind": "summary"}, "distance": .8}]
            return [{"entity": {"talent_id": f"orphan-{i}", "revision": 1, "kind": "summary"}, "distance": .99}
                    for i in range(100)]
    execute_work(work_id, pipeline(RestoredStore()))
    with session() as db:
        results = db.get(MatchRun, run_id).results
        assert len(results) == 1
        assert results[0]["talent_id"] == talent_id

