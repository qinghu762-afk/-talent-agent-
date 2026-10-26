import re
import time
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException, Request
from sqlalchemy import select

from .db import Resource, User

hasher = PasswordHasher()
ROLES = {"admin", "hr", "manager", "employee"}


def workflow_permitted(who, kind):
    allowed = {
        'resume': {'admin', 'hr'}, 'batch': {'admin', 'hr'}, 'job': {'admin', 'hr'},
        'job_import': {'admin', 'hr'}, 'knowledge_import': {'admin', 'hr'},
        'match': {'admin', 'hr', 'manager'}, 'search': {'admin', 'hr', 'manager'},
        'analysis': {'admin', 'manager'},
    }
    return who.get('role') in allowed.get(kind, ROLES)


def authorization_snapshot(who):
    return {key: who.get(key) for key in ('id', 'org_id', 'role', 'auth_version', 'policy_version', 'data_scope', 'denied_fields')}


def public_user(user):
    return {k: getattr(user, k) for k in ("id", "username", "role", "org_id", "talent_id")}


async def resolved_user(db, user):
    who = {**public_user(user), "auth_version": user.token_version}
    policy = await db.scalar(select(Resource).where(Resource.kind == "user-policy", Resource.owner_id == user.id))
    if policy:
        template = await db.get(Resource, policy.data.get("role_template_id", ""))
        if template and template.kind == "roles" and not template.data.get("deleted"):
            who.update({"role_template_id": template.id, "role_name": template.data.get("name"),
                        "permissions": template.data.get("permissions"), "denied_fields": template.data.get("denied_fields", []),
                        "data_scope": template.data.get("data_scope", "org"), "policy_version": template.revision})
    return who


def verify_password(password, hashed):
    try:
        return hasher.verify(hashed, password)
    except (VerificationError, TypeError):
        return False


def issue(user, config):
    return jwt.encode({"sub": user.id, "ver": user.token_version, "jti": str(uuid.uuid4()), "iat": int(time.time()), "exp": int(time.time()) + 8 * 3600}, config.jwt_secret, algorithm="HS256")


async def actor(request: Request):
    token = request.cookies.get("talent_session")
    if not token:
        raise HTTPException(401, "请先登录")
    try:
        claims = jwt.decode(token, request.app.state.config.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "登录已过期")
    if request.app.state.redis:
        if not await request.app.state.redis.exists("session:" + claims["jti"]):
            raise HTTPException(401, "登录已退出")
    async with request.app.state.stores.business() as db:
        user = await db.scalar(select(User).where(User.id == claims["sub"]))
        if not user or not user.active or claims["ver"] != user.token_version:
            raise HTTPException(401, "账号不可用")
        request.state.actor = await resolved_user(db, user)
        request.state.claims = claims
        return request.state.actor


def require(who, *roles):
    if who["role"] not in roles:
        raise HTTPException(403, "无操作权限")


def visible(who, row):
    if (getattr(row, "data", {}) or {}).get("deleted"):
        return False
    if who.get("data_scope") == "self":
        data = getattr(row, "data", {}) or {}
        if row.owner_id != who["id"] and row.id != who.get("talent_id") and data.get("talent_id") != who.get("talent_id"):
            return False
    if who["role"] == "admin":
        return True
    # Analysis can aggregate several organizations. Its storage organization is
    # not the authorization scope of the underlying data or historical columns.
    kind = getattr(row, 'kind', '')
    if kind == 'analysis':
        if row.owner_id != who['id'] or authorization_snapshot(getattr(row, 'actor', {})) != authorization_snapshot(who):
            return False
    if kind == 'reports':
        if row.owner_id != who['id'] or row.data.get('authorization') != authorization_snapshot(who):
            return False
    if row.org_id != who["org_id"]:
        return False
    data = getattr(row, "data", {}) or {}
    if data.get("scope") == "private" and row.owner_id != who["id"]:
        return False
    if who["role"] != "employee":
        return True
    kind = getattr(row, "kind", "")
    if kind in {"knowledge", "courses"}:
        return data.get("scope") != "private" or row.owner_id == who["id"]
    return row.owner_id == who["id"] or row.id == who.get("talent_id") or data.get("talent_id") == who.get("talent_id")


def redact(value, who):
    denied = set(who.get("denied_fields", []))
    hidden_values = set()
    def gather(v, hidden=False):
        if isinstance(v, dict):
            for k, x in v.items():
                gather(x, hidden or k in denied)
        elif isinstance(v, list):
            for x in v:
                gather(x, hidden)
        elif hidden and isinstance(v, str) and len(v) >= 2:
            hidden_values.add(v)
    gather(value)
    def custom_clean(v):
        if isinstance(v, dict):
            return {k: custom_clean(x) for k, x in v.items() if k not in denied}
        if isinstance(v, list):
            return [custom_clean(x) for x in v if not isinstance(x, dict) or str(x.get("field", "")).split(".")[0] not in denied]
        if isinstance(v, str):
            for hidden in sorted(hidden_values, key=len, reverse=True):
                v = v.replace(hidden, "[字段已隐藏]")
        return v
    value = custom_clean(value)
    if who["role"] in {"admin", "hr"}:
        return value
    def clean(v):
        if isinstance(v, dict):
            blocked = {"phone", "email", "password", "password_hash", "source_text", "text", "raw_text", "path", "token", "api_key", "question_snapshot", "rubric"}
            if "question_type" in v:
                blocked.add("answer")
            return {k: clean(x) for k, x in v.items() if k not in blocked}
        if isinstance(v, list):
            return [clean(x) for x in v if not isinstance(x, dict) or str(x.get("field", "")).split(".")[0] not in {"phone", "email"}]
        if isinstance(v, str):
            return re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)(?:\+?86[- ]?)?1[3-9](?:[- ]?\d){9}(?!\d)|\+[1-9][\d ()-]{7,20}\d", "[联系方式已隐藏]", v)
        return v
    # Employees may read their own learning content, but not personal contact evidence.
    result = clean(value)
    if who["role"] == "employee" and isinstance(value, dict) and "content" in value:
        result["content"] = value["content"]
    return result
