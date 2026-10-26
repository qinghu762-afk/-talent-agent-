import asyncio
import csv
import io
import json
import secrets
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import httpx
import jwt
import redis.asyncio as redis
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import Audit, Document, Event, Record, Resource, Run, Stores, User, now, uid
from .security import ROLES, actor, hasher, issue, redact, require, resolved_user, verify_password, visible, workflow_permitted
from .tasks import enqueue, event, output_run
from .uploads import save_file, validated_files

PG_RESOURCES = {"talents", "questions", "assessments", "courses", "training-plans", "knowledge", "issues", "revisions", "merges", "reports", "memories", "assessment-results", "learning-events"}
MY_RESOURCES = {"organizations", "roles", "jobs", "skills", "automations", "approvals", "notifications"}
RESOURCES = PG_RESOURCES | MY_RESOURCES
EMPLOYEE_LIST = {"talents", "assessments", "courses", "training-plans", "knowledge", "notifications", "runs"}
MANAGED = {"organizations", "roles", "skills", "automations"}


def serialize(row):
    return {**row.data, "id": row.id, "org_id": row.org_id, "owner_id": row.owner_id, "revision": row.revision,
            **({"indexed_revision": row.indexed_revision} if isinstance(row, Record) else {})}


def session_for(stores, kind):
    return (stores.facts, Record) if kind in PG_RESOURCES else (stores.business, Resource)


async def resource(stores, who, kind, ident, lock=False):
    factory, model = session_for(stores, kind)
    async with factory() as db:
        q = select(model).where(model.id == ident, model.kind == kind)
        if lock:
            q = q.with_for_update()
        row = await db.scalar(q)
        if not row or not visible(who, row):
            raise HTTPException(404, "记录不存在")
        return row


async def listed(stores, who, kind):
    factory, model = session_for(stores, kind)
    async with factory() as db:
        q = select(model).where(model.kind == kind)
        if who["role"] != "admin":
            q = q.where(model.org_id == who["org_id"])
        rows = (await db.scalars(q.order_by(model.created_at.desc()))).all()
        return [row for row in rows if visible(who, row)]


async def put(stores, who, kind, body, ident=None):
    factory, model = session_for(stores, kind)
    async with factory() as db:
        if ident:
            row = await db.scalar(select(model).where(model.id == ident, model.kind == kind).with_for_update())
            if not row or not visible(who, row):
                raise HTTPException(404, "记录不存在")
            if kind == 'talents' and isinstance(body.get('profile'), dict):
                body = {**body, 'profile': {**row.data.get('profile', {}), **body['profile']}}
            row.data = {**row.data, **body}
            row.revision += 1
            if isinstance(row, Record):
                row.indexed_revision = 0
        else:
            org = body.pop("org_id", None) or who["org_id"]
            if who["role"] != "admin" and org != who["org_id"]:
                raise HTTPException(403, "不能指定其他组织")
            row = model(kind=kind, org_id=org, owner_id=who["id"], data=body)
            db.add(row)
        if kind in {"talents", "knowledge"}:
            await db.flush()
            if kind == "talents":
                db.add(Record(kind="revisions", org_id=row.org_id, owner_id=who["id"], data={"talent_id": row.id, "revision": row.revision, "profile": json.loads(json.dumps(row.data.get("profile", {}))), "operation": "manual_update" if ident else "manual_create", "verified_by": who["id"]}))
            index_kind = "index" if kind == "talents" else "knowledge"
            payload = {"talent_id" if kind == "talents" else "document_id": row.id}
            if row.data.get("deleted"):
                index_kind = "delete_index"
                payload = {"id": row.id, "kind": "talent" if kind == "talents" else "knowledge", "org_id": row.org_id}
            pending = Run(org_id=who["org_id"], owner_id=who["id"], actor=who, kind=index_kind, payload=payload, priority=20)
            db.add(pending)
            await db.flush()
            await event(db, pending)
            row._index_run_id = pending.id
        await db.commit()
        return row


def create_app():
    config = settings()

    @asynccontextmanager
    async def lifespan(app):
        if len(config.jwt_secret) < 32 or len(config.admin_password) < 12 or not config.internal_service_key:
            raise RuntimeError("请配置强 JWT_SECRET、ADMIN_PASSWORD 和 INTERNAL_SERVICE_KEY")
        stores = Stores(config)
        app.state.config = config
        app.state.stores = stores
        app.state.redis = None
        app.state.local_limits = {}
        await stores.initialize()
        config.data_dir.mkdir(parents=True, exist_ok=True)
        if not config.testing:
            app.state.redis = redis.from_url(config.redis_url, decode_responses=True)
            await app.state.redis.ping()
            stores.redis = app.state.redis
        async with stores.business() as db:
            if not await db.scalar(select(User).where(User.username == "admin")):
                db.add(User(username="admin", password_hash=hasher.hash(config.admin_password), role="admin"))
            if not await db.scalar(select(Resource).where(Resource.id == "default")):
                db.add(Resource(id="default", kind="organizations", org_id="default", owner_id="system", data={"name": "默认组织"}))
            await db.commit()
        yield
        if app.state.redis:
            await app.state.redis.aclose()
        await stores.close()

    app = FastAPI(title="AI 数字化人才平台", version="0.2.0", lifespan=lifespan)

    @app.middleware("http")
    async def boundary(request, call_next):
        request.state.request_id = uid()
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            host_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
            if origin not in config.allowed_origins.split(",") + [host_origin]:
                return JSONResponse({"code": "forbidden", "message": "来源校验失败", "data": None, "request_id": request.state.request_id}, 403)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.method not in {"GET", "HEAD", "OPTIONS"} and hasattr(request.state, "actor"):
            who = request.state.actor
            async with app.state.stores.business() as db:
                # No request bodies, raw resumes, contact details or credentials in audit logs.
                db.add(Audit(actor_id=who["id"], org_id=who["org_id"], action=request.method + " " + (request.scope.get("route").path if request.scope.get("route") else request.url.path), target_id="", request_id=request.state.request_id))
                await db.commit()
        return response

    @app.exception_handler(HTTPException)
    async def errors(request, exc):
        return JSONResponse({"code": "error", "message": str(exc.detail), "data": None, "request_id": request.state.request_id}, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation(request, exc):
        return JSONResponse({"code": "validation_error", "message": "输入格式无效", "data": None, "request_id": request.state.request_id}, 422)

    @app.exception_handler(IntegrityError)
    async def duplicate(request, exc):
        return JSONResponse({"code": "conflict", "message": "记录重复或已被并发修改", "data": None, "request_id": request.state.request_id}, 409)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        # Do not expose SQL parameters, documents or credential validation values.
        return JSONResponse({"code": "internal_error", "message": "服务暂时不可用，请凭请求标识联系管理员", "data": None, "request_id": request.state.request_id}, 503)

    def ok(request, value, status=200):
        # All JSON routes share the same final field-permission boundary,
        # including business actions and PATCH responses.
        if hasattr(request.state, 'actor'):
            value = redact(value, request.state.actor)
        return JSONResponse({"code": "ok", "data": value, "request_id": request.state.request_id}, status)

    async def limit(request, key, maximum=120, seconds=60):
        if app.state.redis:
            key = "limit:" + key + ":" + str(int(time.time()) // seconds)
            count = await app.state.redis.incr(key)
            if count == 1:
                await app.state.redis.expire(key, seconds + 1)
        else:
            k = (key, int(time.time()) // seconds)
            count = app.state.local_limits[k] = app.state.local_limits.get(k, 0) + 1
        if count > maximum:
            raise HTTPException(429, "请求过于频繁")

    async def authed(request: Request, who=Depends(actor)):
        await limit(request, who["id"])
        denied = {str(field).casefold() for field in who.get('denied_fields', [])}
        from email.message import Message
        media_type = Message()
        content_type = request.headers.get('content-type')
        media_type['content-type'] = content_type or ''
        json_body = not content_type or (media_type.get_content_maintype() == 'application' and
                    (media_type.get_content_subtype() == 'json' or media_type.get_content_subtype().endswith('+json')))
        if denied and request.method in {'POST', 'PUT', 'PATCH'} and json_body:
            def touches_hidden(value):
                if isinstance(value, dict):
                    return any(str(key).casefold() in denied or touches_hidden(piece) for key, piece in value.items()) or (
                        isinstance(value.get('field'), str) and value['field'].split('.')[0].casefold() in denied)
                return isinstance(value, list) and any(touches_hidden(piece) for piece in value)
            body = await request.body()
            if body and touches_hidden(await request.json()):
                raise HTTPException(403, '当前角色不能修改受限字段')
        if who.get("permissions") is not None:
            from fnmatch import fnmatchcase
            root_resource = request.url.path.removeprefix("/api/v1/").split("/", 1)[0]
            operation = request.method + ":" + root_resource
            if root_resource != "auth" and not any(fnmatchcase(operation, p) for p in who["permissions"]):
                raise HTTPException(403, "自定义角色未授权此操作")
        return who

    router = APIRouter(prefix="/api/v1")

    @app.get("/health")
    @router.get("/health")
    async def health():
        return {"status": "ok", "version": "0.2.0"}

    @router.post("/auth/login")
    async def login(request: Request, body: dict):
        await limit(request, "login:" + (request.client.host if request.client else "local"), 15, 300)
        async with app.state.stores.business() as db:
            user = await db.scalar(select(User).where(User.username == body.get("username", "")))
            if not user or not user.active or not verify_password(body.get("password", ""), user.password_hash):
                raise HTTPException(401, "账号或密码错误")
            token = issue(user, config)
            if app.state.redis:
                claims = jwt.decode(token, config.jwt_secret, algorithms=["HS256"])
                await app.state.redis.setex("session:" + claims["jti"], 28800, user.id)
            current_user = await resolved_user(db, user)
            result = ok(request, current_user)
            result.set_cookie("talent_session", token, max_age=28800, httponly=True, secure=config.cookie_secure, samesite="strict", path="/")
            request.state.actor = current_user
            return result

    @router.get("/auth/me")
    async def me(request: Request, who=Depends(authed)):
        return ok(request, who)

    @router.post("/auth/logout")
    async def logout(request: Request, who=Depends(authed)):
        if app.state.redis:
            await app.state.redis.delete("session:" + request.state.claims["jti"])
        else:
            async with app.state.stores.business() as db:
                user = await db.get(User, who["id"])
                user.token_version += 1
                await db.commit()
        result = ok(request, {"logged_out": True})
        result.delete_cookie("talent_session")
        return result

    @router.get("/users")
    async def users(request: Request, who=Depends(authed)):
        require(who, "admin")
        async with app.state.stores.business() as db:
            values = [await resolved_user(db, u) | {"active": bool(u.active)} for u in (await db.scalars(select(User))).all()]
        return ok(request, {"items": values, "total": len(values)})

    @router.post("/users")
    async def add_user(request: Request, body: dict, who=Depends(authed)):
        require(who, "admin")
        if body.get("role", "employee") not in ROLES or len(body.get("password", "")) < 12 or not body.get("username"):
            raise HTTPException(422, "账号、角色或密码不符合要求（密码至少12位）")
        if body.get("talent_id"):
            await resource(app.state.stores, who, "talents", body["talent_id"])
        template = await resource(app.state.stores, who, "roles", body["role_template_id"]) if body.get("role_template_id") else None
        async with app.state.stores.business() as db:
            user = User(username=body["username"], password_hash=hasher.hash(body["password"]), role=template.data["base_role"] if template else body.get("role", "employee"), org_id=body.get("org_id") or who["org_id"], talent_id=body.get("talent_id"))
            db.add(user)
            await db.flush()
            if template:
                db.add(Resource(kind="user-policy", org_id=user.org_id, owner_id=user.id, data={"role_template_id": template.id}))
            await db.commit()
            return ok(request, await resolved_user(db, user), 201)

    @router.patch("/users/{ident}")
    async def update_user(ident: str, request: Request, body: dict, who=Depends(authed)):
        require(who, "admin")
        async with app.state.stores.business() as db:
            user = await db.get(User, ident)
            if not user:
                raise HTTPException(404, "账号不存在")
            if ident == who["id"] and (body.get("active") is False or body.get("role", "admin") != "admin"):
                raise HTTPException(422, "不能停用或降级当前管理员")
            for key in ("role", "org_id", "talent_id", "active"):
                if key in body:
                    if key == "role" and body[key] not in ROLES:
                        raise HTTPException(422, "角色无效")
                    setattr(user, key, body[key])
            if "password" in body:
                if len(body["password"]) < 12:
                    raise HTTPException(422, "密码至少12位")
                user.password_hash = hasher.hash(body["password"])
            if "role_template_id" in body:
                policy = await db.scalar(select(Resource).where(Resource.kind == "user-policy", Resource.owner_id == ident))
                template = await db.get(Resource, body["role_template_id"]) if body["role_template_id"] else None
                if body["role_template_id"] and (not template or template.kind != "roles"):
                    raise HTTPException(422, "角色模板不存在")
                if ident == who["id"]:
                    raise HTTPException(422, "当前管理员不能限制自己的管理权限")
                if template:
                    user.role = template.data["base_role"]
                    if policy:
                        policy.data = {"role_template_id": template.id}
                    else:
                        db.add(Resource(kind="user-policy", org_id=user.org_id, owner_id=user.id, data={"role_template_id": template.id}))
                elif policy:
                    await db.delete(policy)
            user.token_version += 1
            await db.commit()
            return ok(request, await resolved_user(db, user))

    @router.get("/dashboard")
    async def dashboard(request: Request, who=Depends(authed)):
        counts = {}
        for kind in ("talents", "jobs", "assessments", "training-plans", "knowledge", "issues"):
            counts[kind.replace("-plans", "")] = len(await listed(app.state.stores, who, kind))
        async with app.state.stores.facts() as db:
            runs = [r for r in (await db.scalars(select(Run))).all() if visible(who, r)]
        return ok(request, {"counts": counts, **counts, "runs": len(runs)})

    @router.get("/system")
    async def system(request: Request, who=Depends(authed)):
        require(who, "admin")
        services = []
        async with httpx.AsyncClient(timeout=3) as client:
            for name, url in (("AI 工作流", config.ai_service_url), ("数据分析", config.analytics_service_url), ("文档解析", config.parser_url)):
                try:
                    r = await client.get(url + "/health")
                    services.append({"name": name, "status": "ok" if r.is_success else "error"})
                except httpx.HTTPError:
                    services.append({"name": name, "status": "unavailable"})
        return ok(request, {"services": services, "models": {"chat": config.chat_model, "embedding": config.embedding_model}, "limits": {"batch_files": 200, "file_mb": 20}, "dify_url": config.dify_public_url})

    @router.get("/audits")
    async def audits(request: Request, who=Depends(authed)):
        require(who, "admin", "manager")
        async with app.state.stores.business() as db:
            q = select(Audit).order_by(Audit.created_at.desc()).limit(1000)
            if who["role"] != "admin":
                q = q.where(Audit.org_id == who["org_id"])
            rows = (await db.scalars(q)).all()
        return ok(request, {"items": [{"id": r.id, "actor_id": r.actor_id, "action": r.action, "request_id": r.request_id, "created_at": r.created_at.isoformat()} for r in rows], "total": len(rows)})

    @router.post("/talents/text")
    async def resume_text(request: Request, body: dict, who=Depends(authed)):
        require(who, "admin", "hr")
        text = body.get("text", "")
        if not isinstance(text, str) or not text.strip() or len(text) > 1_000_000:
            raise HTTPException(422, "简历文本为空或过长")
        digest, path = save_file(config.data_dir, "resume.txt", text.encode())
        run = await enqueue(app.state.stores, who, "resume", {"text": text, "filename": "resume.txt", "sha256": digest, "path": path}, 30)
        return ok(request, {"id": run.id}, 202)

    @router.post("/talents/import")
    async def import_files(request: Request, files: list[UploadFile] = File(...), who=Depends(authed)):
        require(who, "admin", "hr")
        content = []
        for upload in files:
            value = await upload.read(config.max_file_bytes + 1)
            content.append((upload.filename or "resume.txt", value))
        validated = validated_files(content, config)
        entries = []
        for name, blob in validated:
            digest, path = save_file(config.data_dir, name, blob)
            entries.append({"filename": name, "sha256": digest, "path": path})
        run = await enqueue(app.state.stores, who, "batch", {"files": entries}, 40)
        return ok(request, {"id": run.id, "count": len(entries)}, 202)

    @router.post("/talents/search")
    async def talent_search(request: Request, body: dict, who=Depends(authed)):
        require(who, "admin", "hr", "manager")
        if not str(body.get("query", "")).strip():
            raise HTTPException(422, "检索条件不能为空")
        run = await enqueue(app.state.stores, who, "search", {"query": body["query"]}, 2)
        return ok(request, {"id": run.id}, 202)

    @router.get("/talents/{ident}/growth")
    async def growth(ident: str, request: Request, who=Depends(authed)):
        await resource(app.state.stores, who, "talents", ident)
        exams = [r for r in await listed(app.state.stores, who, "assessments") if r.data.get("talent_id") == ident]
        plans = [r for r in await listed(app.state.stores, who, "training-plans") if r.data.get("talent_id") == ident]
        plan_ids = {p.id for p in plans}
        events = [r for r in await listed(app.state.stores, {**who, "role": "hr"} if who["role"] == "employee" else who, "learning-events") if r.data.get("plan_id") in plan_ids]
        assessments = [{"id": e.id, "title": e.data.get("title"), "status": e.data.get("status"), "total": e.data.get("total"), "revision": e.revision, "created_at": e.created_at.isoformat()} for e in exams]
        trend = [{"at": e["created_at"], "total": e["total"]} for e in reversed(assessments) if e["total"] is not None]
        return ok(request, {"talent_id": ident, "assessments": assessments, "plans": [serialize(p) for p in plans], "events": [serialize(e) for e in events], "trend": trend})

    @router.get("/documents/{ident}/file")
    async def original(ident: str, request: Request, who=Depends(authed)):
        async with app.state.stores.facts() as db:
            doc = await db.get(Document, ident)
            if not doc or not visible(who, doc):
                raise HTTPException(404, "原文件不存在")
            require(who, "admin", "hr")
            if who.get("denied_fields"):
                raise HTTPException(403, "当前字段权限不能访问未经脱敏的原文件")
            path = Path(doc.path).resolve()
            if not path.is_relative_to(config.data_dir.resolve()) or not path.is_file():
                raise HTTPException(404, "原文件不可用")
            return FileResponse(path, filename=doc.filename, media_type="application/octet-stream")

    @router.post("/jobs/parse")
    async def parse_job(request: Request, body: dict, who=Depends(authed)):
        require(who, "admin", "hr")
        if not body.get("description", "").strip():
            raise HTTPException(422, "岗位描述不能为空")
        run = await enqueue(app.state.stores, who, "job", body, 5)
        return ok(request, {"id": run.id}, 202)

    @router.post("/jobs/import")
    async def job_file(request: Request, file: UploadFile = File(...), who=Depends(authed)):
        require(who, "admin", "hr")
        form = await request.form()
        entries = validated_files([(file.filename or "job.txt", await file.read(config.max_file_bytes + 1))], config)
        if len(entries) != 1:
            raise HTTPException(422, "岗位文件请逐个导入")
        name, blob = entries[0]
        digest, path = save_file(config.data_dir, name, blob)
        run = await enqueue(app.state.stores, who, "job_import", {"filename": name, "path": path, "sha256": digest, "title": str(form.get("title") or name)}, 5)
        return ok(request, {"id": run.id}, 202)

    @router.post("/jobs/{ident}/match")
    async def match_job(ident: str, request: Request, who=Depends(authed)):
        require(who, "admin", "hr", "manager")
        job = await resource(app.state.stores, who, "jobs", ident)
        req = job.data.get("requirements", {})
        if not any(req.get(k) for k in ("required_skills", "preferred_skills", "min_experience_months", "responsibilities", "projects", "project_requirements", "bonus")):
            raise HTTPException(422, "岗位没有有效评分条件，请补充技能或职责")
        run = await enqueue(app.state.stores, who, "match", {"job_id": ident}, 1)
        return ok(request, {"id": run.id}, 202)

    @router.post("/assessments/{ident}/publish")
    async def publish(ident: str, request: Request, who=Depends(authed)):
        require(who, "admin", "hr")
        exam = await resource(app.state.stores, who, "assessments", ident)
        if exam.data.get("status", "draft") != "draft":
            raise HTTPException(409, "测评已提交发布")
        if not exam.data.get("question_ids"):
            raise HTTPException(422, "试卷没有题目")
        snapshot = [serialize(await resource(app.state.stores, who, "questions", ident)) for ident in exam.data["question_ids"]]
        approval = await put(app.state.stores, who, "approvals", {"kind": "assessment_publish", "target_id": ident, "status": "pending", "title": exam.data.get("title")})
        await put(app.state.stores, who, "assessments", {"status": "waiting_approval", "approval_id": approval.id, "question_snapshot": snapshot}, ident)
        from .notifications import notify
        await notify(app.state.stores, key=approval.id, org_id=exam.org_id, title="测评发布待审批", message=exam.data.get("title", "测评"), target="approvals", managers=True)
        return ok(request, serialize(approval), 201)

    @router.post("/assessments/compose")
    async def compose_exam(request: Request, body: dict, who=Depends(authed)):
        require(who, "admin", "hr")
        from .ai_domain import canonical_skill
        talent = await resource(app.state.stores, who, "talents", body.get("talent_id", ""))
        skills = list(talent.data.get("profile", {}).get("skills", []))
        if body.get("job_id"):
            job = await resource(app.state.stores, who, "jobs", body["job_id"])
            skills = job.data.get("requirements", {}).get("required_skills", []) + job.data.get("requirements", {}).get("preferred_skills", [])
        wanted = {canonical_skill(s).casefold() for s in skills}
        questions = await listed(app.state.stores, who, "questions")
        questions.sort(key=lambda q: (-len(wanted & {canonical_skill(s).casefold() for s in q.data.get("skills", [])}), secrets.randbelow(1000000)))
        count = body.get("question_count", 10)
        if not isinstance(count, int) or not 1 <= count <= 100 or len(questions) < count:
            raise HTTPException(422, "题库数量不足或题量无效（1—100）")
        exam = await put(app.state.stores, who, "assessments", {"title": body.get("title") or "岗位能力测评", "talent_id": talent.id, "question_ids": [q.id for q in questions[:count]], "duration_minutes": max(1, min(180, int(body.get("duration_minutes", 30)))), "job_id": body.get("job_id"), "status": "draft", "assembly_skills": sorted(wanted)})
        return ok(request, serialize(exam), 201)

    @router.post("/approvals/{ident}/resolve")
    async def approve(ident: str, request: Request, body: dict, who=Depends(authed)):
        require(who, "admin", "manager")
        approval = await resource(app.state.stores, who, "approvals", ident)
        if approval.data.get("status") != "pending":
            raise HTTPException(409, "审批已处理")
        approved = body.get("approved")
        if not isinstance(approved, bool):
            raise HTTPException(422, "请选择批准或拒绝")
        target = approval.data["target_id"]
        if approval.data["kind"] == "assessment_publish":
            await put(app.state.stores, who, "assessments", {"status": "published" if approved else "draft"}, target)
            if approved:
                from .notifications import notify
                exam = await resource(app.state.stores, who, "assessments", target)
                await notify(app.state.stores, key=approval.id, org_id=exam.org_id, title="新的测评任务", message="测评已经发布，请在测评中心开始作答。", talent_id=exam.data.get("talent_id"), target="assessments")
        elif approval.data["kind"] == "assessment_rating":
            await put(app.state.stores, who, "assessments", {"status": "rated" if approved else "review_required", "rating_approved": approved}, target)
            if approval.data.get("run_id"):
                async with app.state.stores.facts() as db:
                    run = await db.get(Run, approval.data["run_id"])
                    if run and run.status == "waiting_approval":
                        run.status = "succeeded" if approved else "failed"
                        await event(db, run, approval_id=ident)
                        await db.commit()
            if approved:
                exam = await resource(app.state.stores, who, "assessments", target)
                talent = await resource(app.state.stores, who, "talents", exam.data["talent_id"])
                await put(app.state.stores, who, "talents", {"rating": {"total": exam.data.get("total"), "assessment_id": target, "inference": True, "evidence": exam.data.get("result", {}), "approved_by": who["id"]}}, talent.id)
                if float(exam.data.get("total") or 0) < 80 and await listed(app.state.stores, who, "courses"):
                    import uuid
                    ident_run = str(uuid.uuid5(uuid.UUID(approval.id), "training"))
                    async with app.state.stores.facts() as db:
                        if not await db.get(Run, ident_run):
                            followup = Run(id=ident_run, org_id=exam.org_id, owner_id=who["id"], actor=who, kind="training", payload={"talent_id": talent.id, "assessment_id": target}, priority=10)
                            db.add(followup)
                            await db.flush()
                            await event(db, followup)
                            await db.commit()
        result = await put(app.state.stores, who, "approvals", {"status": "approved" if approved else "rejected", "reviewer_id": who["id"], "comment": str(body.get("comment", ""))[:2000]}, ident)
        return ok(request, serialize(result))

    async def questions_for(who, exam):
        if exam.data.get("question_snapshot"):
            return [{k: v for k, v in q.items() if k not in {"answer", "rubric"}} for q in exam.data["question_snapshot"]]
        questions = []
        for ident in exam.data.get("question_ids", []):
            row = await resource(app.state.stores, {**who, "role": "hr"} if who["role"] == "employee" else who, "questions", ident)
            questions.append({k: v for k, v in serialize(row).items() if k not in {"answer", "rubric"}})
        return questions

    @router.post("/assessments/{ident}/start")
    async def start_assessment(ident: str, request: Request, who=Depends(authed)):
        factory, model = session_for(app.state.stores, "assessments")
        async with factory() as db:
            exam = await db.scalar(select(model).where(model.id == ident, model.kind == "assessments").with_for_update())
            if not exam or not visible(who, exam):
                raise HTTPException(404, "测评不存在")
            if exam.data.get("status") not in {"published", "started"}:
                raise HTTPException(409, "测评尚未发布或已结束")
            if exam.data.get("status") == "published":
                exam.data = {**exam.data, "status": "started", "started_at": now().isoformat(), "deadline": (now() + timedelta(minutes=exam.data.get("duration_minutes", 30))).isoformat()}
                await db.commit()
            questions = await questions_for(who, exam)
            return ok(request, redact({**serialize(exam), "questions": questions}, who))

    @router.post("/assessments/{ident}/submit")
    async def submit(ident: str, request: Request, body: dict, who=Depends(authed)):
        async with app.state.stores.facts() as db:
            exam = await db.scalar(select(Record).where(Record.id == ident, Record.kind == "assessments").with_for_update())
            if not exam or not visible(who, exam):
                raise HTTPException(404, "测评不存在")
            if exam.data.get("status") != "started":
                raise HTTPException(409, "测评未开始或已提交")
            answers = body.get("answers", {})
            if not isinstance(answers, dict) or not set(answers).issubset(set(exam.data["question_ids"])):
                raise HTTPException(422, "答题内容无效")
            events = [e for e in body.get("events", []) if isinstance(e, dict) and e.get("type") in {"blur", "focus", "copy", "paste", "visibility", "timeout"}][:1000]
            if now().isoformat() > exam.data["deadline"]:
                events.append({"type": "timeout", "at": now().isoformat()})
            run = Run(org_id=who["org_id"], owner_id=who["id"], actor=who, kind="assessment", payload={"assessment_id": ident, "answers": answers, "events": events}, priority=3)
            db.add(run)
            await db.flush()
            await event(db, run)
            exam.data = {**exam.data, "status": "submitted", "run_id": run.id, "submitted_at": now().isoformat()}
            await db.commit()
            return ok(request, {"id": run.id}, 202)

    @router.get("/assessments/{ident}/result")
    async def assessment_result(ident: str, request: Request, who=Depends(authed)):
        exam = await resource(app.state.stores, who, "assessments", ident)
        if not exam.data.get("run_id"):
            raise HTTPException(409, "测评尚未提交")
        async with app.state.stores.facts() as db:
            run = await db.get(Run, exam.data["run_id"])
            return ok(request, redact(output_run(run), who))

    @router.post("/assessments/{ident}/retest")
    async def retest(ident: str, request: Request, who=Depends(authed)):
        require(who, "admin", "hr")
        exam = await resource(app.state.stores, who, "assessments", ident)
        new = {k: v for k, v in exam.data.items() if k in {"title", "talent_id", "question_ids", "duration_minutes"}}
        new.update({"parent_id": ident, "status": "draft", "title": new.get("title", "测评") + "（复测）"})
        return ok(request, serialize(await put(app.state.stores, who, "assessments", new)), 201)

    @router.post("/training-plans/recommend")
    async def training_recommend(request: Request, body: dict, who=Depends(authed)):
        await resource(app.state.stores, who, "talents", body.get("talent_id", ""))
        run = await enqueue(app.state.stores, who, "training", {k: v for k, v in body.items() if k in {"talent_id", "assessment_id"}}, 5)
        return ok(request, {"id": run.id}, 202)

    @router.post("/training-plans/{ident}/progress")
    async def learning_progress(ident: str, request: Request, body: dict, who=Depends(authed)):
        plan = await resource(app.state.stores, who, "training-plans", ident)
        course_id = body.get("course_id")
        if course_id not in plan.data.get("course_ids", []):
            raise HTTPException(422, "课程不属于该计划")
        course = await resource(app.state.stores, who, "courses", course_id)
        duration = int(course.data.get("duration_seconds", 0))
        position = body.get("position_seconds", 0)
        if not isinstance(position, (int, float)) or position < 0 or position > duration:
            raise HTTPException(422, "进度无效")
        progress = {**plan.data.get("progress", {})}
        prior = progress.get(course_id, {})
        elapsed = max(0, (now() - __import__("datetime").datetime.fromisoformat(prior.get("at", now().isoformat()))).total_seconds())
        allowed = prior.get("position_seconds", 0) + elapsed + 15
        anomaly = position > allowed
        progress[course_id] = {"position_seconds": min(position, allowed), "at": now().isoformat(), "completed": position >= duration and not anomaly}
        result = await put(app.state.stores, who, "training-plans", {"progress": progress, "status": "completed" if all(progress.get(c, {}).get("completed") for c in plan.data["course_ids"]) else "learning"}, ident)
        await put(app.state.stores, who, "learning-events", {"plan_id": ident, "course_id": course_id, "position_seconds": position, "anomaly": anomaly})
        return ok(request, serialize(result))

    @router.post("/training-plans/{ident}/quiz")
    async def course_quiz(ident: str, request: Request, body: dict, who=Depends(authed)):
        plan = await resource(app.state.stores, who, "training-plans", ident)
        course_id = body.get("course_id")
        if course_id not in plan.data.get("course_ids", []):
            raise HTTPException(422, "课程不属于该计划")
        if not plan.data.get("progress", {}).get(course_id, {}).get("completed"):
            raise HTTPException(409, "请先完成课程学习")
        course = await resource(app.state.stores, who, "courses", course_id)
        questions = course.data.get("quiz", [])
        if not questions:
            raise HTTPException(422, "该课程未设置考核题目")
        answers = body.get("answers", {})
        if not isinstance(answers, dict) or not set(answers).issubset({str(q["id"]) for q in questions}):
            raise HTTPException(422, "考核答案无效")
        earned, maximum = 0, 0
        for q in questions:
            points = float(q.get("points", 1))
            maximum += points
            given, expected = answers.get(str(q["id"])), q.get("answer")
            passed = isinstance(given, list) and isinstance(expected, list) and set(given) == set(expected) if q.get("question_type") == "multiple" else given is not None and given == expected
            earned += points if passed else 0
        score = round(100 * earned / maximum, 2) if maximum else 0
        quizzes = {**plan.data.get("quizzes", {})}
        result = {"score": score, "passed": score >= 80, "attempt": quizzes.get(course_id, {}).get("attempt", 0) + 1, "threshold": 80}
        quizzes[course_id] = result
        await put(app.state.stores, who, "training-plans", {"quizzes": quizzes}, ident)
        await put(app.state.stores, who, "learning-events", {"plan_id": ident, "course_id": course_id, "kind": "quiz", "answers": answers, "result": result})
        return ok(request, result)

    @router.post("/knowledge/text")
    async def knowledge_text(request: Request, body: dict, who=Depends(authed)):
        require(who, "admin", "hr")
        if not body.get("text", "").strip() or not body.get("title") or body.get("scope", "org") not in {"org", "private", "company"}:
            raise HTTPException(422, "资料标题、正文或范围无效")
        row = await put(app.state.stores, who, "knowledge", {k: v for k, v in body.items() if k in {"title", "text", "scope"}})
        return ok(request, {**serialize(row), "run_id": row._index_run_id}, 201)

    @router.post("/knowledge")
    async def knowledge_file(request: Request, file: UploadFile = File(...), who=Depends(authed)):
        require(who, "admin", "hr")
        form = await request.form()
        scope = str(form.get("scope", "org"))
        if scope not in {"org", "private", "company"}:
            raise HTTPException(422, "资料范围无效")
        value = await file.read(config.max_file_bytes + 1)
        entries = validated_files([(file.filename or "document.txt", value)], config)
        if len(entries) != 1:
            raise HTTPException(422, "知识文件请逐个导入")
        name, value = entries[0]
        digest, path = save_file(config.data_dir, name, value)
        run = await enqueue(app.state.stores, who, "knowledge_import", {"filename": name, "path": path, "sha256": digest, "title": str(form.get("title") or name), "scope": scope}, 20)
        return ok(request, {"id": run.id, "run_id": run.id}, 202)

    @router.post("/chat")
    async def chat(request: Request, body: dict, who=Depends(authed)):
        if not str(body.get("question", "")).strip():
            raise HTTPException(422, "问题不能为空")
        if body.get("talent_id"):
            await resource(app.state.stores, who, "talents", body["talent_id"])
        run = await enqueue(app.state.stores, who, "chat", {"question": body["question"], "talent_id": body.get("talent_id"), "session_id": body.get("session_id") or uid()}, 2)
        return ok(request, {"id": run.id}, 202)

    @router.post("/analysis")
    async def analysis(request: Request, body: dict, who=Depends(authed)):
        require(who, "admin", "manager")
        if who.get("data_scope") == "self":
            raise HTTPException(403, "仅个人数据范围的角色不能执行组织统计")
        if not body.get("question") or body.get("datasource", "postgres") not in {"postgres", "mysql"}:
            raise HTTPException(422, "问题或数据源无效")
        run = await enqueue(app.state.stores, who, "analysis", {"question": body["question"], "datasource": body.get("datasource", "postgres"), "session_id": body.get("session_id") or uid()}, 3)
        return ok(request, {"id": run.id}, 202)

    @router.post("/skills/{ident}/execute")
    async def execute_skill(ident: str, request: Request, body: dict, who=Depends(authed)):
        skill = await resource(app.state.stores, who, "skills", ident)
        if not workflow_permitted(who, skill.data.get('handler')):
            raise HTTPException(403, "当前角色不能执行该技能处理器")
        if not skill.data.get("enabled", True):
            raise HTTPException(409, "技能已停用")
        run = await enqueue(app.state.stores, who, "skill", {"skill_id": ident, "parameters": body.get("parameters", {})}, 5)
        return ok(request, {"id": run.id}, 202)

    @router.post("/integrations/dify/skills/execute")
    async def dify_skill(request: Request, body: dict):
        if not secrets.compare_digest(request.headers.get("X-Service-Key", ""), config.internal_service_key):
            raise HTTPException(401, "工具鉴权失败")
        async with app.state.stores.business() as db:
            skill = await db.get(Resource, body.get("skill_id", ""))
            if not skill or skill.kind != "skills" or not skill.data.get("enabled", True) or not skill.data.get("config", {}).get("allow_dify", False):
                raise HTTPException(404, "该工具未授权给 Dify")
            user = await db.get(User, skill.owner_id)
            if not user or not user.active or user.org_id != skill.org_id:
                raise HTTPException(403, "工具所属账号不可用")
            who = await resolved_user(db, user)
            if body.get("org_id") and body["org_id"] != who["org_id"]:
                raise HTTPException(403, "工具组织不匹配")
            # Actor and allowed data scopes are never accepted from the tool payload.
            request.state.actor = who
            run = await enqueue(app.state.stores, who, "skill", {"skill_id": skill.id, "parameters": body.get("parameters", {})}, 5)
            return ok(request, {"id": run.id}, 202)

    @router.get("/runs")
    async def runs(request: Request, who=Depends(authed)):
        async with app.state.stores.facts() as db:
            q = select(Run).order_by(Run.created_at.desc()).limit(1000)
            if who["role"] != "admin":
                q = q.where(Run.org_id == who["org_id"])
            rows = [r for r in (await db.scalars(q)).all() if visible(who, r)]
        return ok(request, {"items": [await authorized_result(r, who) for r in rows], "total": len(rows)})

    @router.get('/integrations/dify/runs/{ident}')
    async def dify_result(ident: str, request: Request):
        if not secrets.compare_digest(request.headers.get('X-Service-Key', ''), config.internal_service_key):
            raise HTTPException(401, '工具鉴权失败')
        async with app.state.stores.facts() as db:
            parent = await db.get(Run, ident)
            if not parent or parent.kind != 'skill':
                raise HTTPException(404, '技能运行不存在')
            child_id = parent.result.get('child_run_id')
            child = await db.get(Run, child_id) if child_id else None
        async with app.state.stores.business() as db:
            skill = await db.get(Resource, parent.payload.get('skill_id', ''))
            user = await db.get(User, parent.owner_id)
            if (not skill or skill.kind != 'skills' or skill.owner_id != parent.owner_id or
                    not skill.data.get('enabled', True) or not skill.data.get('config', {}).get('allow_dify')):
                raise HTTPException(404, '技能未授权给Dify')
            if not user or not user.active or user.org_id != skill.org_id or parent.org_id != skill.org_id:
                raise HTTPException(403, '工具所属账号或组织不可用')
            who = await resolved_user(db, user)
        if not workflow_permitted(who, skill.data.get('handler')):
            raise HTTPException(403, '当前角色不能执行该工具')
        if child and (child.owner_id != parent.owner_id or child.org_id != parent.org_id):
            raise HTTPException(404, '子任务不存在')
        request.state.actor = who
        chosen = child or parent
        if not visible(who, chosen):
            raise HTTPException(403, '任务的当前数据权限已变更')
        return ok(request, {**(await authorized_result(chosen, who)), 'id': parent.id, 'child_run_id': child_id})

    async def get_run(ident, who):
        async with app.state.stores.facts() as db:
            run = await db.get(Run, ident)
            if not run or not visible(who, run):
                raise HTTPException(404, "任务不存在")
            return run

    async def authorized_result(run, who):
        result = output_run(run)
        value = json.loads(json.dumps(result["result"], default=str))
        if run.kind == 'batch' and value.get('files'):
            async with app.state.stores.facts() as db:
                children = (await db.scalars(select(Run).where(Run.id.in_([item['id'] for item in value['files']])))).all()
            children = {child.id: child for child in children if child.payload.get('parent_id') == run.id and visible(who, child)}
            value['files'] = [{**item, 'status': children[item['id']].status, 'error': children[item['id']].error}
                              if item['id'] in children else item for item in value['files']]
            value['settled'] = sum(item['status'] in {'succeeded', 'failed', 'cancelled'} for item in value['files'])
            value['failed'] = sum(item['status'] == 'failed' for item in value['files'])
            result['progress'] = round(100 * value['settled'] / max(1, len(value['files'])), 2)
        if run.kind in {"match", "search"}:
            permitted = []
            key = "items" if run.kind == "search" else "candidates"
            for candidate in value.get(key, []):
                try:
                    await resource(app.state.stores, who, "talents", candidate["talent_id"])
                    permitted.append(candidate)
                except HTTPException:
                    pass
            value[key] = permitted
            if run.kind == "search":
                value["total"] = len(permitted)
        if run.kind == "chat":
            async with app.state.stores.facts() as db:
                for citation in value.get("citations", []):
                    doc = await db.get(Record, citation.get("source_id"))
                    if not doc or not visible(who, doc):
                        value = {"answer": "引用资料的当前权限已变更，请重新提问。", "citations": [], "session_id": value.get("session_id")}
                        break
        result["result"] = value
        return redact(result, who)

    @router.get("/runs/{ident}")
    async def run_detail(ident: str, request: Request, who=Depends(authed)):
        return ok(request, await authorized_result(await get_run(ident, who), who))

    @router.post("/runs/{ident}/cancel")
    async def cancel(ident: str, request: Request, who=Depends(authed)):
        await get_run(ident, who)
        async with app.state.stores.facts() as db:
            run = await db.scalar(select(Run).where(Run.id == ident).with_for_update())
            if run.status in {"succeeded", "failed", "cancelled"}:
                raise HTTPException(409, "任务已经结束")
            run.status = "cancelled"
            await event(db, run)
            if run.kind == "batch":
                children = (await db.scalars(select(Run).where(Run.org_id == run.org_id, Run.kind == "resume").with_for_update())).all()
                for child in children:
                    if child.payload.get("parent_id") == ident and child.status not in {"succeeded", "failed", "cancelled"}:
                        child.status = "cancelled"
                        await event(db, child)
            await db.commit()
        return ok(request, {"id": ident, "status": "cancelled"})

    @router.get("/runs/{ident}/events")
    async def events(ident: str, request: Request, who=Depends(authed)):
        await get_run(ident, who)
        try:
            after = int(request.headers.get("last-event-id", "0"))
        except ValueError:
            raise HTTPException(422, "事件序号无效")
        async def stream():
            nonlocal after
            for _ in range(300):
                if await request.is_disconnected():
                    return
                await get_run(ident, await actor(request))
                async with app.state.stores.facts() as db:
                    rows = (await db.scalars(select(Event).where(Event.run_id == ident, Event.seq > after).order_by(Event.seq))).all()
                    run = await db.get(Run, ident)
                for e in rows:
                    after = e.seq
                    yield f"id: {e.seq}\nevent: progress\ndata: {json.dumps(e.data, ensure_ascii=False)}\n\n"
                if run.status in {"succeeded", "failed", "cancelled", "waiting_approval"}:
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.get("/matches/{ident}/export.csv")
    async def export_match(ident: str, request: Request, who=Depends(authed)):
        require(who, "admin", "hr", "manager")
        run = await get_run(ident, who)
        if run.kind != "match" or run.status != "succeeded":
            raise HTTPException(409, "匹配结果尚未完成")
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["人才ID", "姓名", "适配分", "评分证据"])
        for row in run.result.get("candidates", []):
            # Recheck present-day row permission even for historical results.
            await resource(app.state.stores, who, "talents", row["talent_id"])
            def safe(v):
                s = str(v)
                return "'" + s if s[:1] in {"=", "+", "-", "@"} else s
            writer.writerow([safe(row["talent_id"]), safe(row.get("name", "")), row.get("score", {}).get("total", 0), safe(json.dumps(redact(row.get("score", {}), who), ensure_ascii=False))])
        return Response("\ufeff" + stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=matches.csv"})

    @router.get("/reports/{ident}/export")
    async def export_report(ident: str, request: Request, format: str = "docx", who=Depends(authed)):
        require(who, "admin", "manager")
        report = await resource(app.state.stores, who, "reports", ident)
        if format not in {"pdf", "docx"}:
            raise HTTPException(422, "仅支持 Word/PDF")
        from .reports import render_report
        content = await asyncio.to_thread(render_report, redact(report.data, who), format)
        return Response(content, media_type="application/pdf" if format == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f"attachment; filename=report.{format}"})

    @router.post("/merges/{ident}/undo")
    async def undo_merge(ident: str, request: Request, who=Depends(authed)):
        require(who, "admin", "hr")
        from .persistence import undo_merge as undo
        result = await undo(app.state.stores, who, ident)
        return ok(request, result)

    # Static routes above intentionally precede generic resource routes.
    @router.get("/{kind}")
    async def list_resource(kind: str, request: Request, who=Depends(authed)):
        if kind not in RESOURCES:
            raise HTTPException(404, "资源不存在")
        if who["role"] == "employee" and kind not in EMPLOYEE_LIST:
            raise HTTPException(403, "无查看权限")
        if kind in MANAGED:
            require(who, "admin")
        rows = await listed(app.state.stores, who, kind)
        return ok(request, {"items": [redact(serialize(r), who) for r in rows], "total": len(rows)})

    @router.post("/{kind}")
    async def create_resource(kind: str, request: Request, body: dict, who=Depends(authed)):
        if kind not in RESOURCES or kind in {"merges", "revisions", "assessment-results", "learning-events", "reports", "memories", "approvals"}:
            raise HTTPException(404, "资源不存在")
        require(who, "admin") if kind in MANAGED else require(who, "admin", "hr")
        value = {k: v for k, v in body.items() if k not in {"id", "owner_id", "revision", "indexed_revision", "approval_id", "run_id"}}
        if kind == "talents":
            value["profile"] = {**value.get("profile", {}), "source": "manual", "verified_by": who["id"]}
        if kind == "roles":
            if value.get("base_role") not in ROLES or value.get("data_scope", "org") not in {"org", "self"} or not value.get("name"):
                raise HTTPException(422, "角色名称、基础角色或数据范围无效")
            if value.get("permissions") is not None and (not isinstance(value["permissions"], list) or any(not isinstance(p, str) or ":" not in p for p in value["permissions"])):
                raise HTTPException(422, "操作权限应为 METHOD:资源名 数组")
        if kind in {"assessments", "training-plans"}:
            await resource(app.state.stores, who, "talents", value.get("talent_id", ""))
            for ident in value.get("question_ids" if kind == "assessments" else "course_ids", []):
                await resource(app.state.stores, who, "questions" if kind == "assessments" else "courses", ident)
            value["status"] = "draft" if kind == "assessments" else "assigned"
        if kind == "questions" and (value.get("question_type") not in {"single", "multiple", "text"} or not value.get("title") or float(value.get("points", 0)) <= 0):
            raise HTTPException(422, "题目类型、标题或分值无效")
        if kind == "courses":
            if not value.get("title") or int(value.get("duration_seconds", 0)) <= 0:
                raise HTTPException(422, "课程标题和时长必填")
            quiz = value.get("quiz", [])
            for q in quiz:
                if not isinstance(q, dict) or q.get("question_type") not in {"single", "multiple"} or "answer" not in q or float(q.get("points", 1)) <= 0:
                    raise HTTPException(422, "课后考核仅支持有效分值的单选或多选题")
                q["id"] = str(q.get("id") or uid())
        if kind == "skills" and value.get("handler") not in {"resume", "job", "match", "assessment", "chat", "training", "analysis"}:
            raise HTTPException(422, "技能处理器不在允许列表")
        if kind == "automations":
            await resource(app.state.stores, who, "skills", value.get("skill_id", ""))
            if value.get("trigger", "schedule") not in {"schedule", "event"}:
                raise HTTPException(422, "触发方式无效")
            if value.get("trigger", "schedule") == "event" and value.get("event_kind") not in {"resume", "assessment", "training", "job", "match", "knowledge"}:
                raise HTTPException(422, "事件类型无效")
            if value.get("trigger", "schedule") == "schedule" and int(value.get("interval_seconds", 0)) < 60:
                raise HTTPException(422, "自动化间隔至少60秒")
        row = await put(app.state.stores, who, kind, value)
        return ok(request, serialize(row), 201)

    @router.get("/{kind}/{ident}")
    async def get_resource(kind: str, ident: str, request: Request, who=Depends(authed)):
        if kind not in RESOURCES:
            raise HTTPException(404, "资源不存在")
        if who["role"] == "employee" and kind not in EMPLOYEE_LIST:
            raise HTTPException(403, "无查看权限")
        row = await resource(app.state.stores, who, kind, ident)
        result = serialize(row)
        if kind == "talents" and app.state.redis:
            key = f"profile:{who['org_id']}:{who['id']}:{who.get('auth_version')}:{who.get('policy_version')}:{ident}:{row.revision}"
            try:
                cached = await app.state.redis.get(key)
                if cached:
                    result = json.loads(cached)
                    await app.state.redis.incr("metrics:profile_cache_hits")
                else:
                    await app.state.redis.setex(key, 60, json.dumps(result, ensure_ascii=False))
                    await app.state.redis.incr("metrics:profile_cache_misses")
            except redis.RedisError:
                pass  # Cache failure cannot replace the current authorized PostgreSQL fact.
        if kind == "assessments":
            result.pop("question_snapshot", None)
        if kind == "talents":
            async with app.state.stores.facts() as db:
                docs = (await db.scalars(select(Document).where(Document.talent_id == ident))).all()
                result["documents"] = [{"id": d.id, "filename": d.filename, "model_versions": d.model_versions} for d in docs]
            result["revisions"] = [serialize(r) for r in await listed(app.state.stores, who, "revisions") if r.data.get("talent_id") == ident]
            result["merges"] = [serialize(r) for r in await listed(app.state.stores, who, "merges") if r.data.get("talent_id") == ident]
        if kind == "assessments" and row.data.get("status") in {"published", "started"}:
            result["questions"] = await questions_for(who, row)
        return ok(request, redact(result, who))

    @router.patch("/{kind}/{ident}")
    async def patch_resource(kind: str, ident: str, request: Request, body: dict, who=Depends(authed)):
        if kind not in RESOURCES:
            raise HTTPException(404, "资源不存在")
        if kind == "notifications":
            body = {"read": bool(body.get("read"))}
        else:
            require(who, "admin") if kind in MANAGED else require(who, "admin", "hr")
            if kind in {"approvals", "revisions", "merges", "learning-events", "assessment-results"}:
                raise HTTPException(403, "请通过业务操作修改")
            if any(k in body for k in {"status", "indexed_revision", "owner_id", "org_id", "id", "run_id", "revision", "approval_id", "started_at", "deadline", "progress"}):
                raise HTTPException(422, "不能直接修改流程状态或归属")
            if kind == "talents" and "profile" in body:
                body["profile"] = {**body["profile"], "source": "manual", "verified_by": who["id"]}
        row = await put(app.state.stores, who, kind, body, ident)
        return ok(request, serialize(row))

    @router.delete("/{kind}/{ident}")
    async def delete_resource(kind: str, ident: str, request: Request, who=Depends(authed)):
        require(who, "admin", "hr")
        if kind not in {"talents", "jobs", "knowledge", "courses", "questions"}:
            raise HTTPException(403, "该记录不能删除")
        # Tombstone prevents stale vectors from participating; durable index task removes them.
        await put(app.state.stores, who, kind, {"deleted": True}, ident)
        return ok(request, {"id": ident, "deleted": True})

    app.include_router(router)
    return app


app = create_app()
