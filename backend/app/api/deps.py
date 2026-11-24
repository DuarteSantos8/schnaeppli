from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db, utcnow
from app.core.ratelimit import API_PER_USER, get_limiter
from app.core.security import client_ip, constant_time_equals, token_hash
from app.models import AuditLog, Session, User

SESSION_COOKIE = "schnaeppli_session"
CSRF_COOKIE = "schnaeppli_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Auth:
    user: User
    session: Session


async def current_auth(request: Request, db: AsyncSession = Depends(get_db)) -> Auth:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    row = (
        await db.execute(
            select(Session, User)
            .join(User, User.id == Session.user_id)
            .where(Session.token_hash == token_hash(token))
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    sess, user = row
    now = utcnow()
    settings = get_settings()
    if (
        sess.expires_at < now
        or sess.last_seen_at < now - timedelta(days=settings.session_idle_days)
        or not user.is_active
    ):
        await db.delete(sess)
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    if request.method not in SAFE_METHODS:
        header = request.headers.get(CSRF_HEADER, "")
        if not header or not constant_time_equals(header, sess.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF check failed")

    allowed, retry = await get_limiter().hit(f"api:{user.id}", API_PER_USER)
    if not allowed:
        raise HTTPException(429, "Too many requests", headers={"Retry-After": str(retry)})

    if sess.last_seen_at < now - timedelta(minutes=5):
        sess.last_seen_at = now
        await db.commit()
    return Auth(user=user, session=sess)


async def current_user(auth: Auth = Depends(current_auth)) -> User:
    return auth.user


async def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator only")
    return user


async def audit(
    db: AsyncSession, request: Request | None, event: str, user_id=None, detail: str | None = None
):
    db.add(
        AuditLog(
            user_id=user_id,
            event=event,
            ip=client_ip(request) if request else None,
            detail=(detail or "")[:1000] or None,
        )
    )
