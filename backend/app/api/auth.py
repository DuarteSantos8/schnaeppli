from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CSRF_COOKIE, SESSION_COOKIE, Auth, audit, current_auth, current_user
from app.core.config import get_settings
from app.core.db import get_db, utcnow
from app.core.ratelimit import LOGIN_PER_ACCOUNT, LOGIN_PER_IP, REGISTER_PER_IP, get_limiter
from app.core.security import (
    client_ip,
    constant_time_equals,
    hash_password,
    new_token,
    password_needs_rehash,
    password_problems,
    token_hash,
    verify_password,
)
from app.models import Invite, Session, User
from app.schemas.user import UserOut, user_out

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOCKOUT_AFTER = 10
LOCKOUT_MINUTES = 15


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=80)
    invite_code: str | None = Field(default=None, max_length=100)
    setup_token: str | None = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class AuthStatus(BaseModel):
    setup_required: bool
    setup_token_required: bool
    registration_mode: str
    telegram_bot: str | None


def _set_session_cookies(response: Response, token: str, csrf: str) -> None:
    s = get_settings()
    max_age = s.session_days * 86400
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=s.secure_cookies,
        samesite="lax",
        path="/",
    )
    # Readable by the SPA, echoed back in X-CSRF-Token (double-submit, bound to the session).
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=max_age,
        httponly=False,
        secure=s.secure_cookies,
        samesite="strict",
        path="/",
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


async def _start_session(db: AsyncSession, request: Request, response: Response, user: User) -> None:
    token, csrf = new_token(), new_token(24)
    db.add(
        Session(
            user_id=user.id,
            token_hash=token_hash(token),
            csrf_token=csrf,
            expires_at=utcnow() + timedelta(days=get_settings().session_days),
            ip=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:300],
        )
    )
    user.last_login_at = utcnow()
    _set_session_cookies(response, token, csrf)


@router.get("/status", response_model=AuthStatus)
async def auth_status(db: AsyncSession = Depends(get_db)) -> AuthStatus:
    count = await db.scalar(select(func.count()).select_from(User))
    s = get_settings()
    return AuthStatus(
        setup_required=count == 0,
        setup_token_required=count == 0 and bool(s.setup_token),
        registration_mode=s.registration_mode,
        telegram_bot=s.telegram_bot_username,
    )


@router.post("/register", response_model=UserOut, status_code=201)
async def register(
    body: RegisterIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    ip = client_ip(request)
    allowed, retry = await get_limiter().hit(f"register:{ip}", REGISTER_PER_IP)
    if not allowed:
        raise HTTPException(429, "Too many attempts. Try again later.", headers={"Retry-After": str(retry)})

    email = body.email.lower().strip()
    first_user = (await db.scalar(select(func.count()).select_from(User))) == 0
    mode = get_settings().registration_mode
    invite: Invite | None = None
    expected = get_settings().setup_token
    if first_user and expected and not constant_time_equals((body.setup_token or "").strip(), expected):
        await audit(db, request, "setup_token_rejected", None)
        await db.commit()
        raise HTTPException(403, "The setup token is missing or wrong. It's in the server configuration.")
    if not first_user:
        if mode == "closed":
            raise HTTPException(403, "Registration is closed.")
        if mode == "invite":
            if not body.invite_code:
                raise HTTPException(403, "An invite code is required.")
            invite = await db.scalar(
                select(Invite).where(
                    Invite.code_hash == token_hash(body.invite_code.strip()), Invite.used_by.is_(None)
                )
            )
            if invite is None or invite.expires_at < utcnow():
                raise HTTPException(403, "This invite code is invalid or expired.")

    problems = password_problems(body.password, email)
    if problems:
        raise HTTPException(422, " ".join(problems))
    if await db.scalar(select(User.id).where(User.email == email)):
        # Same wording as a generic failure would leak less, but on an invite-only
        # private instance a clear message is more useful and the invite is the gate.
        raise HTTPException(409, "An account with this e-mail already exists.")

    user = User(
        email=email,
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
        is_admin=first_user,
        timezone=get_settings().default_timezone,
        currency=get_settings().default_currency,
    )
    db.add(user)
    await db.flush()
    if invite:
        invite.used_by, invite.used_at = user.id, utcnow()
    await audit(db, request, "register", user.id, "first user (admin)" if first_user else None)
    await _start_session(db, request, response, user)
    await db.commit()
    return user_out(user)


@router.post("/login", response_model=UserOut)
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ip = client_ip(request)
    email = body.email.lower().strip()
    limiter = get_limiter()
    ok_ip, retry_ip = await limiter.hit(f"login-ip:{ip}", LOGIN_PER_IP)
    ok_acc, retry_acc = await limiter.hit(f"login-acc:{email}", LOGIN_PER_ACCOUNT)
    if not (ok_ip and ok_acc):
        await audit(db, request, "login_rate_limited", None, email)
        await db.commit()
        raise HTTPException(
            429,
            "Too many sign-in attempts. Try again later.",
            headers={"Retry-After": str(max(retry_ip, retry_acc))},
        )

    user = await db.scalar(select(User).where(User.email == email))
    now = utcnow()
    locked = user is not None and user.locked_until is not None and user.locked_until > now
    valid = verify_password(user.password_hash if user else None, body.password)
    if user is None or not valid or locked or not user.is_active:
        if user is not None and not locked:
            user.failed_logins += 1
            if user.failed_logins >= LOCKOUT_AFTER:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                user.failed_logins = 0
                await audit(db, request, "account_locked", user.id)
        await audit(db, request, "login_failed", user.id if user else None, None if user else "unknown email")
        await db.commit()
        raise HTTPException(401, "E-mail or password is incorrect.")

    user.failed_logins = 0
    user.locked_until = None
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    await limiter.reset(f"login-acc:{email}", LOGIN_PER_ACCOUNT)
    await audit(db, request, "login", user.id)
    await _start_session(db, request, response, user)
    await db.commit()
    return user_out(user)


@router.post("/logout", status_code=204)
async def logout(response: Response, auth: Auth = Depends(current_auth), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Session).where(Session.id == auth.session.id))
    await db.commit()
    _clear_cookies(response)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return user_out(user)


@router.post("/password", status_code=204)
async def change_password(
    body: PasswordChangeIn,
    request: Request,
    auth: Auth = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, auth.user.id)
    assert user
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(401, "Current password is incorrect.")
    problems = password_problems(body.new_password, user.email)
    if problems:
        raise HTTPException(422, " ".join(problems))
    user.password_hash = hash_password(body.new_password)
    # Sign out every other device.
    await db.execute(delete(Session).where(Session.user_id == user.id, Session.id != auth.session.id))
    await audit(db, request, "password_changed", user.id)
    await db.commit()


class SessionOut(BaseModel):
    id: str
    created_at: str
    last_seen_at: str
    ip: str | None
    user_agent: str | None
    current: bool


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(auth: Auth = Depends(current_auth), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.scalars(
            select(Session).where(Session.user_id == auth.user.id).order_by(Session.last_seen_at.desc())
        )
    ).all()
    return [
        SessionOut(
            id=str(s.id),
            created_at=s.created_at.isoformat(),
            last_seen_at=s.last_seen_at.isoformat(),
            ip=s.ip,
            user_agent=s.user_agent,
            current=s.id == auth.session.id,
        )
        for s in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: str, auth: Auth = Depends(current_auth), db: AsyncSession = Depends(get_db)
):
    import uuid

    try:
        sid = uuid.UUID(session_id)
    except ValueError as e:
        raise HTTPException(404, "Not found") from e
    await db.execute(delete(Session).where(Session.id == sid, Session.user_id == auth.user.id))
    await db.commit()
