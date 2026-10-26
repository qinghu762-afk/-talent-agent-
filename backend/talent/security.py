import hashlib
import hmac
import secrets
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, Request

from .config import settings
from .db import User, session, utcnow


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def verify_password(password, stored):
    try:
        salt, expected = stored.split(":")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def current_user(request: Request):
    bearer = request.headers.get("authorization", "")
    token = bearer[7:] if bearer.startswith("Bearer ") else request.cookies.get("talent_session")
    if not token:
        raise HTTPException(401, "请先登录")
    # Cookie authentication requires same-origin requests for mutations.
    if not bearer and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "请求来源不匹配")
    try:
        claims = jwt.decode(token, settings().jwt_secret, algorithms=["HS256"])
        with session() as db:
            user = db.get(User, claims["sub"])
            if not user or not user.active or claims.get("ver") != user.token_version:
                raise HTTPException(401, "账号已停用")
            return user
    except (jwt.InvalidTokenError, KeyError):
        raise HTTPException(401, "登录已过期") from None


def admin_user(user=Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "此操作需要管理员权限")
    return user


def issue_token(user):
    return jwt.encode({"sub": user.id, "ver": user.token_version,
                       "exp": utcnow() + timedelta(hours=settings().session_hours)},
                      settings().jwt_secret, algorithm="HS256")

