"""Recoverable jobs backed by the SQL outbox, independently of broker availability."""
import time
from datetime import timedelta

import httpx
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError
from sqlalchemy import and_, case, or_, select

from .adapters import DocumentParser, PrivateModels, VectorStore, vector_chunks
from .db import Document, Issue, Job, MatchRun, Talent, Work, session, uid, utcnow
from .domain import score_candidate
from .repository import ingest_profile
from .schemas import JobRequirements, TalentProfile


class Pipeline:
    def __init__(self, models=None, parser=None, vectors=None):
        self.models = models or PrivateModels()
        self.parser = parser or DocumentParser()
        self.vectors = vectors or VectorStore

    def run(self, kind, payload):
        if kind == "ingest":
            return self.ingest(payload)
        if kind == "index":
            return self.index(payload)
        if kind == "job":
            return self.job(payload)
        if kind == "match":
            return self.match(payload)
        raise ValueError("未知任务类型")

    def ingest(self, payload):
        doc_id = payload["document_id"]
        with session() as db:
            document = db.get(Document, doc_id)
            if not document:
                raise ValueError("文档不存在")
            if document.talent_id:
                return
            document.status = "running"
            text = document.text
            extracted = document.extracted
        if not text:
            text, parser_version = self.parser.parse(document)
            if len(text) > 200000:
                raise ValueError("文档文字超过处理上限")
            with session() as db:
                current = db.get(Document, doc_id)
                current.text = text
                current.model_versions = {"parser": parser_version}
        if extracted is None:
            result = self.models.resume_with_report(text)
            extracted = result.profile.model_dump()
            with session() as db:
                current = db.get(Document, doc_id)
                current.extracted = extracted
                current.model_versions = {**(current.model_versions or {}), **self.models.versions(),
                                          "resume_workflow": result.report.model_dump()}
        with session() as db:
            document = db.get(Document, doc_id)
            ingest_profile(db, document, TalentProfile.model_validate(extracted))

    def index(self, payload):
        with session() as db:
            talent = db.scalar(select(Talent).where(Talent.id == payload["talent_id"]).with_for_update())
            if not talent or talent.revision != payload["revision"]:
                return
            versions = self.models.versions()
            digest = versions["embedding"]["digest"]
            if talent.indexed_revision == talent.revision and talent.index_model == digest:
                return
            chunks = vector_chunks(TalentProfile.model_validate(talent.profile)) if talent.active else []
            vectors = self.models.embed([c["text"] for c in chunks]) if chunks else []
            store = self.vectors(digest)
            store.replace(talent, chunks, vectors)
            # SQL commit happens only after Milvus acknowledged the full current version.
            talent.indexed_revision = talent.revision
            talent.index_model = digest
            if talent.active and vectors:
                for hit in store.search(vectors[0], limit=10):
                    other_id = hit["entity"]["talent_id"]
                    if other_id == talent.id or float(hit["distance"]) < .94:
                        continue
                    other = db.get(Talent, other_id)
                    if not other or not other.active or other.indexed_revision != other.revision:
                        continue
                    exists = db.scalar(select(Issue.id).where(Issue.kind == "similar_resume", or_(
                        and_(Issue.talent_id == talent.id, Issue.other_id == other_id),
                        and_(Issue.talent_id == other_id, Issue.other_id == talent.id))))
                    if not exists:
                        db.add(Issue(talent_id=talent.id, other_id=other_id, kind="similar_resume",
                                     detail="语义相似度较高，身份未证实；已保留独立档案"))

    def job(self, payload):
        with session() as db:
            job = db.get(Job, payload["job_id"])
            if not job or job.revision != payload["revision"] or job.status == "completed":
                return
            job.status = "running"
            description = job.description
            document = db.get(Document, job.document_id) if job.document_id else None
        if document:
            description = document.text
            if not description:
                description, parser_version = self.parser.parse(document)
                with session() as db:
                    db.get(Document, document.id).text = description
        if not description or len(description) > 100000:
            raise ValueError("岗位文档为空或超出长度限制")
        requirements = self.models.job(description)
        with session() as db:
            job = db.scalar(select(Job).where(Job.id == payload["job_id"]).with_for_update())
            if job.revision != payload["revision"]:
                return
            job.description = description
            job.requirements = requirements.model_dump()
            job.status = "completed"

    def match(self, payload):
        started = time.monotonic()
        with session() as db:
            run = db.get(MatchRun, payload["run_id"])
            if not run or run.status == "completed":
                return
            run.status = "running"
            job = run.job_snapshot
        requirements = JobRequirements.model_validate(job["requirements"])
        versions = self.models.versions()
        digest = versions["embedding"]["digest"]
        query = "；".join([job.get("title", "")] + requirements.required_skills + requirements.preferred_skills
                         + requirements.responsibilities + requirements.required_certificates)
        vector = self.models.embed([query or "岗位要求未知"])[0]
        store = self.vectors(digest)
        # Restrict recall before top-k: orphan vectors after restore must not consume the 100 slots.
        with session() as db:
            ready_ids = list(db.scalars(select(Talent.id).where(Talent.active.is_(True),
                             Talent.indexed_revision == Talent.revision, Talent.index_model == digest)))
        hits = store.search(vector, requirements, 100, ids=ready_ids)
        project_hits = store.search(vector, requirements, 100, kind="project",
                                    ids=list({h["entity"]["talent_id"] for h in hits})) if requirements.responsibilities else []
        projects = {(h["entity"]["talent_id"], h["entity"]["revision"]): float(h["distance"])
                    for h in project_hits if h["entity"].get("kind") == "project"}
        results, seen = [], set()
        stale, excluded, unknown = 0, 0, 0
        with session() as db:
            for hit in hits:
                entity = hit["entity"]
                talent_id = entity["talent_id"]
                if talent_id in seen:
                    continue
                seen.add(talent_id)
                talent = db.scalar(select(Talent).where(Talent.id == talent_id).with_for_update())
                if (not talent or not talent.active or talent.indexed_revision != talent.revision
                        or talent.revision != entity["revision"] or talent.index_model != digest):
                    stale += 1
                    continue
                profile = TalentProfile.model_validate(talent.profile)
                score = score_candidate(profile, requirements, projects.get((talent.id, talent.revision), 0))
                if not score.eligible:
                    excluded += 1
                    unknown += bool(score.unknowns)
                    continue
                results.append({"talent_id": talent.id, "name": profile.name or "姓名未知", "revision": talent.revision,
                                "profile": profile.model_dump(), "score": score.model_dump()})
            results.sort(key=lambda r: (-r["score"]["total"], r["talent_id"]))
            run = db.get(MatchRun, payload["run_id"])
            run.results = results[:20]
            run.status = "completed"
            run.duration_ms = int((time.monotonic() - started) * 1000)
            run.model_versions = {**versions, "scoring": "1.0.1", "weights": {"skills": .4, "experience": .25, "projects": .25, "preferred": .1}}
            run.diagnostics = {"recalled": len(seen), "eligible": len(results), "stale_excluded": stale,
                               "hard_excluded": excluded, "unknown_excluded": unknown}


def target_status(db, work, status, error=None):
    payload = work.payload
    if work.kind == "ingest":
        obj = db.get(Document, payload.get("document_id"))
    elif work.kind == "match":
        obj = db.get(MatchRun, payload.get("run_id"))
    elif work.kind == "job":
        obj = db.get(Job, payload.get("job_id"))
        if obj and obj.revision != payload.get("revision"):
            obj = None
    else:
        obj = None
    if obj and obj.status != "completed":
        obj.status = status
        if isinstance(obj, Document):
            obj.error = error


def execute_work(work_id, pipeline=None):
    lease = uid()
    with session() as db:
        work = db.scalar(select(Work).where(Work.id == work_id).with_for_update())
        if not work or work.status not in {"queued", "dispatched", "retry"}:
            return
        available = work.available_at.replace(tzinfo=utcnow().tzinfo) if work.available_at.tzinfo is None else work.available_at
        if available > utcnow():
            return
        work.status, work.lease, work.updated_at = "running", lease, utcnow()
        work.attempts += 1
        kind, payload = work.kind, work.payload
    try:
        (pipeline or Pipeline()).run(kind, payload)
    except Exception as exc:
        invalid_output = isinstance(exc, (ValidationError, OutputParserException))
        permanent = (isinstance(exc, ValueError) and not invalid_output) or (
            isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500
            and exc.response.status_code not in {408, 429})
        error = "文件或结构化信息无法验证，请检查原文及任务类型" if permanent else "本地服务暂时不可用或处理超时，请检查服务状态后重试"
        if invalid_output:
            error = "本地模型结构化输出未通过字段校验，自动重试最多三次"
        with session() as db:
            work = db.get(Work, work_id)
            if work.lease != lease:
                return
            work.status = "failed" if permanent or work.attempts >= 4 else "retry"
            work.error, work.updated_at, work.lease = error, utcnow(), None
            work.available_at = utcnow() + timedelta(seconds=5 * (2 ** (work.attempts - 1)))
            target_status(db, work, work.status, error)
        return
    with session() as db:
        work = db.get(Work, work_id)
        if work.lease == lease:
            work.status, work.error, work.lease, work.updated_at = "completed", None, None, utcnow()


def dispatch_pending(publish):
    now = utcnow()
    # Publish only a bounded window. DB remains the durable source if Redis is unavailable.
    with session() as db:
        expired = db.scalars(select(Work).where(Work.status == "running", Work.updated_at < now - timedelta(seconds=1900)).with_for_update())
        for work in expired:
            work.status = "failed" if work.attempts >= 4 else "retry"
            work.lease, work.available_at = None, now
            work.error = "工作进程中断，任务已恢复或达到重试上限"
            target_status(db, work, work.status, work.error)
        pending = db.scalars(select(Work).where(or_(
            and_(Work.status.in_(["queued", "retry"]), Work.available_at <= now),
            and_(Work.status == "dispatched", Work.updated_at < now - timedelta(seconds=60))))
            .order_by(case((Work.kind == "match", 0), (Work.kind == "job", 1), (Work.kind == "index", 2), else_=3),
                      Work.created_at).limit(64).with_for_update(skip_locked=True)).all()
        pending.sort(key=lambda w: {"match": 0, "job": 1, "index": 2, "ingest": 3}.get(w.kind, 4))
        for work in pending:
            # An uncommitted publish may be delivered before the row update; claim accepts queued too.
            publish(work.id, work.kind)
            work.status, work.updated_at = "dispatched", now
    return len(pending)
