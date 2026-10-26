"""Authenticated API. Slow inference is exclusively executed by the single worker."""
import csv
import hashlib
import io
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Literal

import httpx
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from .config import settings
from .db import (
    Audit,
    Base,
    Batch,
    BatchItem,
    Document,
    Issue,
    Job,
    MatchRun,
    Merge,
    Revision,
    Talent,
    User,
    Work,
    engine,
    session,
    utcnow,
)
from .repository import enqueue, identity_lock, snapshot, undo_merge, update_talent
from .schemas import JobRequirements, TalentProfile
from .security import admin_user, current_user, hash_password, issue_token, verify_password
from .storage import UploadRejected, expand_uploads, persist_file


def row_dict(row, exclude=()):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns if column.name not in exclude}


def public_user(user):
    return row_dict(user, {"password_hash", "token_version"})


def initialize():
    config = settings()
    if len(config.jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET 至少需要 32 个随机字符，请先运行启动脚本生成配置")
    Base.metadata.create_all(engine())
    with session() as db:
        identity_lock(db)
        if not db.scalar(select(User.id).where(User.role == "admin")):
            if len(config.admin_password) < 12:
                raise RuntimeError("首次启动需要至少 12 位的 ADMIN_PASSWORD")
            db.add(User(username=config.admin_username, password_hash=hash_password(config.admin_password), role="admin"))


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(title="人才工作台", version="0.1.0", lifespan=lifespan,
              docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json", redoc_url=None)
router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_user)])


@app.middleware("http")
async def request_limits(request: Request, call_next):
    if int(request.headers.get("content-length", "0")) > settings().max_batch_bytes + 1024 * 1024:
        return JSONResponse({"detail": "请求超过 200MB 批次限制"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "mode": "private"}


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@app.post("/api/v1/auth/login")
def login(body: LoginInput, request: Request, response: Response):
    key = hashlib.sha256(((request.client.host if request.client else "local") + body.username).encode()).hexdigest()
    with session() as db:
        failures = db.scalar(select(func.count()).select_from(Audit).where(
            Audit.actor == key, Audit.action == "login_failure", Audit.created_at > utcnow() - timedelta(minutes=15)))
        if failures >= 5:
            raise HTTPException(429, "登录失败次数过多，请 15 分钟后重试")
        user = db.scalar(select(User).where(User.username == body.username))
        valid = verify_password(body.password, user.password_hash if user else "00" * 16 + ":" + "00" * 64)
        if not user or not user.active or not valid:
            db.add(Audit(actor=key, action="login_failure"))
            # Commit failure counters before returning an error (raising here would roll back).
            db.flush()
            failure = True
        else:
            failure = False
            token = issue_token(user)
            result = public_user(user)
            db.add(Audit(actor=user.id, action="login", target_id=user.id))
    if failure:
        raise HTTPException(401, "账号或密码错误")
    response.set_cookie("talent_session", token, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", max_age=settings().session_hours * 3600, path="/")
    return {"user": result}


@router.get("/auth/me")
def me(user=Depends(current_user)):
    return public_user(user)


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie("talent_session", path="/")
    return {"ok": True}


@router.get("/dashboard")
def dashboard():
    with session() as db:
        def count(model, *conditions):
            return db.scalar(select(func.count()).select_from(model).where(*conditions))
        return {"talents": count(Talent, Talent.active.is_(True)),
                "indexed": count(Talent, Talent.active.is_(True), Talent.revision == Talent.indexed_revision),
                "jobs": count(Job), "documents": count(Document),
                "queued": count(Work, Work.status.in_(["queued", "running", "retry"])),
                "failed": count(Work, Work.status == "failed"), "issues": count(Issue, Issue.resolved.is_(False))}


def batch_dict(db, batch):
    items = db.scalars(select(BatchItem).where(BatchItem.batch_id == batch.id).order_by(BatchItem.created_at)).all()
    output = []
    for item in items:
        doc = db.get(Document, item.document_id) if item.document_id else None
        output.append({"id": item.id, "filename": item.filename,
                       "status": "failed" if item.error else doc.status if doc else "failed",
                       "error": item.error or (doc.error if doc else None), "reused": item.reused,
                       "talent_id": doc.talent_id if doc else None})
    return {"id": batch.id, "created_at": batch.created_at, "items": output}


async def read_files(files):
    data, total = [], 0
    if len(files) > settings().max_batch_files:
        raise HTTPException(413, "每批最多 200 个文件")
    for upload in files:
        try:
            pieces = []
            while chunk := await upload.read(512 * 1024):
                total += len(chunk)
                if total > settings().max_batch_bytes:
                    raise HTTPException(413, "每批上传不能超过 200MB")
                pieces.append(chunk)
            data.append((upload.filename or "unnamed", b"".join(pieces)))
        finally:
            await upload.close()
    try:
        return expand_uploads(data)
    except UploadRejected as exc:
        raise HTTPException(400, str(exc)) from None


def register_document(db, incoming):
    digest, path = persist_file(incoming)
    existing = db.scalar(select(Document).where(Document.sha256 == digest))
    if existing:
        return existing, True
    document = Document(sha256=digest, filename=incoming.filename, path=path, size=len(incoming.content))
    db.add(document)
    db.flush()
    return document, False


@router.post("/batches", status_code=201)
async def create_batch(files: list[UploadFile] = File(...), user=Depends(current_user)):
    incoming = await read_files(files)
    with session() as db:
        identity_lock(db)
        batch = Batch(owner_id=user.id)
        db.add(batch)
        db.flush()
        for file in incoming:
            if file.error:
                db.add(BatchItem(batch_id=batch.id, filename=file.filename, error=file.error))
                continue
            doc, reused = register_document(db, file)
            # A document first uploaded as a JD can later be ingested as a resume.
            has_work = db.scalar(select(Work.id).where(Work.kind == "ingest", Work.subject_id == doc.id))
            if not doc.talent_id and not has_work:
                enqueue(db, "ingest", {"document_id": doc.id})
                doc.status = "queued"
            db.add(BatchItem(batch_id=batch.id, document_id=doc.id, filename=file.filename, reused=reused))
        db.flush()
        return batch_dict(db, batch)


@router.get("/batches")
def batches():
    with session() as db:
        return [batch_dict(db, b) for b in db.scalars(select(Batch).order_by(Batch.created_at.desc()).limit(50))]


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: str):
    with session() as db:
        batch = db.get(Batch, batch_id)
        if not batch:
            raise HTTPException(404, "批次不存在")
        return batch_dict(db, batch)


@router.get("/tasks")
def tasks():
    with session() as db:
        return [row_dict(w, {"payload", "lease"}) for w in db.scalars(select(Work).order_by(Work.created_at.desc()).limit(200))]


@router.post("/tasks/{work_id}/retry")
def retry(work_id: str, user=Depends(current_user)):
    with session() as db:
        work = db.scalar(select(Work).where(Work.id == work_id).with_for_update())
        if not work:
            raise HTTPException(404, "任务不存在")
        if work.status != "failed":
            raise HTTPException(409, "只有失败任务可以手动重试")
        work.status, work.attempts, work.error = "queued", 0, None
        work.available_at, work.updated_at = utcnow(), utcnow()
        if work.kind == "ingest":
            doc = db.get(Document, work.payload["document_id"])
            doc.status, doc.error = "queued", None
        db.add(Audit(actor=user.id, action="retry", target_id=work.id))
        return {"id": work.id, "status": work.status}


@router.get("/talents")
def talents(q: str = Query("", max_length=200), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    with session() as db:
        conditions = [Talent.active.is_(True)]
        if q:
            conditions.append((Talent.name.icontains(q, autoescape=True)) | (Talent.phone.icontains(q, autoescape=True))
                              | (Talent.email.icontains(q, autoescape=True)))
        total = db.scalar(select(func.count()).select_from(Talent).where(*conditions))
        rows = db.scalars(select(Talent).where(*conditions).order_by(Talent.created_at.desc())
                          .offset((page - 1) * page_size).limit(page_size))
        return {"items": [row_dict(t) for t in rows], "total": total}


def get_talent(db, talent_id):
    talent = db.scalar(select(Talent).where(Talent.id == talent_id).with_for_update())
    if not talent or not talent.active:
        raise HTTPException(404, "人才档案不存在")
    return talent


@router.get("/talents/{talent_id}")
def talent_detail(talent_id: str):
    with session() as db:
        talent = get_talent(db, talent_id)
        return {**row_dict(talent), "documents": [row_dict(d, {"path", "text", "extracted"}) for d in
                db.scalars(select(Document).where(Document.talent_id == talent_id))],
                "revisions": [row_dict(r) for r in db.scalars(select(Revision).where(Revision.talent_id == talent_id)
                                                              .order_by(Revision.revision.desc()))],
                "merges": [row_dict(m, {"before_profile", "incoming_profile"}) for m in
                           db.scalars(select(Merge).where(Merge.talent_id == talent_id))]}


class TalentEdit(BaseModel):
    profile: TalentProfile
    revision: int = Field(ge=1)


@router.put("/talents/{talent_id}")
def talent_edit(talent_id: str, body: TalentEdit, user=Depends(current_user)):
    with session() as db:
        identity_lock(db)
        talent = get_talent(db, talent_id)
        updated = body.profile.model_dump()
        changed = {key for key in ("name", "phone", "email", "location", "education", "experiences", "projects",
                                   "skills", "certificates", "intentions") if talent.profile.get(key) != updated[key]}
        body.profile.evidence = {key: value for key, value in TalentProfile.model_validate(talent.profile).evidence.items()
                                 if key.split(".")[0] not in changed}
        if changed:
            body.profile.anomalies.append("部分字段经人工校正，操作者和变更详情见历史版本")
        update_talent(db, talent, body.profile, body.revision, "人工编辑，操作者 " + user.username)
        db.add(Audit(actor=user.id, action="edit_talent", target_id=talent_id))
        return row_dict(talent)


@router.delete("/talents/{talent_id}")
def talent_delete(talent_id: str, user=Depends(current_user)):
    with session() as db:
        identity_lock(db)
        talent = get_talent(db, talent_id)
        snapshot(db, talent, "归档人才")
        talent.active, talent.indexed_revision = False, 0
        talent.revision += 1
        enqueue(db, "index", {"talent_id": talent_id, "revision": talent.revision})
        db.add(Audit(actor=user.id, action="archive_talent", target_id=talent_id))
        return {"ok": True}


@router.get("/documents/{document_id}/file")
def original_file(document_id: str):
    with session() as db:
        doc = db.get(Document, document_id)
        if not doc:
            raise HTTPException(404, "原文件不存在")
        path = Path(doc.path).resolve()
        root = (settings().data_dir / "originals").resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404, "原文件不可用，请检查文件备份")
        return FileResponse(path, filename=doc.filename, content_disposition_type="attachment")


@router.get("/issues")
def issues():
    with session() as db:
        return [row_dict(i) for i in db.scalars(select(Issue).order_by(Issue.resolved, Issue.created_at.desc()).limit(500))]


@router.post("/issues/{issue_id}/resolve")
def resolve_issue(issue_id: str, user=Depends(current_user)):
    with session() as db:
        issue = db.get(Issue, issue_id)
        if not issue:
            raise HTTPException(404, "记录不存在")
        issue.resolved = True
        db.add(Audit(actor=user.id, action="resolve_issue", target_id=issue_id))
        return {"ok": True}


@router.post("/merges/{merge_id}/undo")
def merge_undo(merge_id: str, user=Depends(current_user)):
    with session() as db:
        record = db.get(Merge, merge_id)
        if not record:
            raise HTTPException(404, "合并记录不存在")
        restored = undo_merge(db, record)
        db.add(Audit(actor=user.id, action="undo_merge", target_id=merge_id))
        return {"talent_id": record.talent_id, "new_talent_id": restored.id}


class JobInput(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1, max_length=100000)


@router.post("/jobs", status_code=201)
def create_job(body: JobInput):
    with session() as db:
        job = Job(**body.model_dump())
        db.add(job)
        db.flush()
        work = enqueue(db, "job", {"job_id": job.id, "revision": job.revision})
        return {"id": job.id, "task_id": work.id}


@router.post("/jobs/upload", status_code=201)
async def upload_job(title: str = Form(..., min_length=1, max_length=256), file: UploadFile = File(...)):
    incoming = await read_files([file])
    if len(incoming) != 1 or incoming[0].error:
        raise HTTPException(400, "岗位文件必须为单个有效文档")
    with session() as db:
        identity_lock(db)
        document, _ = register_document(db, incoming[0])
        job = Job(title=title, description="", document_id=document.id)
        db.add(job)
        db.flush()
        work = enqueue(db, "job", {"job_id": job.id, "revision": job.revision})
        return {"id": job.id, "task_id": work.id}


@router.get("/jobs")
def jobs():
    with session() as db:
        return [row_dict(j) for j in db.scalars(select(Job).order_by(Job.created_at.desc()).limit(200))]


class JobEdit(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    requirements: JobRequirements
    revision: int = Field(ge=1)


@router.put("/jobs/{job_id}")
def edit_job(job_id: str, body: JobEdit, user=Depends(current_user)):
    with session() as db:
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if not job:
            raise HTTPException(404, "岗位不存在")
        if job.revision != body.revision:
            raise HTTPException(409, "岗位版本已变化，请刷新")
        job.title, job.requirements = body.title, body.requirements.model_dump()
        job.revision += 1
        job.status = "completed"
        db.add(Audit(actor=user.id, action="edit_job", target_id=job_id))
        return row_dict(job)


@router.post("/jobs/{job_id}/matches", status_code=202)
def create_match(job_id: str):
    with session() as db:
        job = db.get(Job, job_id)
        if not job:
            raise HTTPException(404, "岗位不存在")
        if job.status != "completed" or job.requirements is None:
            raise HTTPException(409, "请等待岗位解析完成，或先编辑岗位要求")
        run = MatchRun(job_id=job.id, job_snapshot={"title": job.title, "description": job.description,
                                                   "requirements": job.requirements, "revision": job.revision})
        db.add(run)
        db.flush()
        work = enqueue(db, "match", {"run_id": run.id})
        return {"id": run.id, "task_id": work.id}


@router.get("/jobs/{job_id}/matches")
def job_matches(job_id: str):
    with session() as db:
        return [row_dict(r) for r in db.scalars(select(MatchRun).where(MatchRun.job_id == job_id)
                                               .order_by(MatchRun.created_at.desc()).limit(50))]


@router.get("/matches/{run_id}")
def match_detail(run_id: str):
    with session() as db:
        run = db.get(MatchRun, run_id)
        if not run:
            raise HTTPException(404, "匹配记录不存在")
        return row_dict(run)


def csv_safe(value):
    value = str(value or "")
    return "'" + value if value.lstrip(" ").startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value


@router.get("/matches/{run_id}/export.csv")
def export_match(run_id: str):
    run = match_detail(run_id)
    if run["status"] != "completed":
        raise HTTPException(409, "匹配尚未完成")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["排名", "姓名", "适配分", "人才ID", "档案版本", "优势", "缺口", "未知", "评分依据"])
    for index, result in enumerate(run["results"] or []):
        score = result["score"]
        values = [index + 1, result["name"], score["total"], result["talent_id"], result["revision"],
                  "；".join(score["strengths"]), "；".join(score["gaps"]), "；".join(score["unknowns"]),
                  "；".join(d["label"] + "：" + " / ".join(d["evidence"]) for d in score["dimensions"])]
        writer.writerow([csv_safe(v) for v in values])
    return StreamingResponse(iter([output.getvalue().encode("utf-8-sig")]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="match-{run_id}.csv"'})


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[\w.@-]+$")
    password: str = Field(min_length=12, max_length=256)
    role: Literal["admin", "recruiter"] = "recruiter"


class UserEdit(BaseModel):
    active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)
    role: Literal["admin", "recruiter"] | None = None


@router.get("/users", dependencies=[Depends(admin_user)])
def users():
    with session() as db:
        return [public_user(u) for u in db.scalars(select(User).order_by(User.created_at))]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, actor=Depends(admin_user)):
    with session() as db:
        identity_lock(db)
        if db.scalar(select(User.id).where(User.username == body.username)):
            raise HTTPException(409, "账号已存在")
        user = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
        db.add(user)
        db.flush()
        db.add(Audit(actor=actor.id, action="create_user", target_id=user.id))
        return public_user(user)


@router.put("/users/{user_id}")
def edit_user(user_id: str, body: UserEdit, actor=Depends(admin_user)):
    with session() as db:
        identity_lock(db)
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "账号不存在")
        if user.role == "admin" and (body.active is False or body.role == "recruiter"):
            admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.active.is_(True)))
            if admins <= 1:
                raise HTTPException(409, "至少保留一个可用管理员")
        for key in ("role", "active"):
            if getattr(body, key) is not None:
                setattr(user, key, getattr(body, key))
        if body.password:
            user.password_hash = hash_password(body.password)
            user.token_version += 1
        db.add(Audit(actor=actor.id, action="edit_user", target_id=user.id))
        return public_user(user)


@router.get("/system")
def system_status():
    config = settings()
    services = {}
    def probe(name, action):
        try:
            action()
            services[name] = {"ok": True, "detail": "服务可用"}
        except Exception:
            services[name] = {"ok": False, "detail": "服务不可用，请检查本机服务及模型准备状态"}
    def postgres():
        with session() as db:
            db.execute(text("SELECT 1"))
    def redis():
        from redis import Redis
        Redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2).ping()
    def url_check(url):
        with httpx.Client(timeout=2, trust_env=False) as client:
            client.get(url).raise_for_status()
    def milvus():
        from pymilvus import MilvusClient
        client = MilvusClient(uri=config.milvus_url, timeout=2)
        try:
            client.list_collections(timeout=2)
        finally:
            client.close()
    probe("postgres", postgres)
    probe("redis", redis)
    probe("ollama", lambda: url_check(config.ollama_url + "/api/tags"))
    probe("mineru", lambda: url_check(config.mineru_url + "/health"))
    probe("milvus", milvus)
    return {"mode": "private", "services": services, "models": {"chat": config.chat_model, "embedding": config.embedding_model},
            "limits": {"batch_files": config.max_batch_files, "file_mb": config.max_file_bytes // 1024 // 1024}}


app.include_router(router)
