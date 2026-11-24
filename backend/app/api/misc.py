"""Chat, notifications/Telegram, sources, dashboard and admin endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import gateway
from app.ai.providers import ProviderError
from app.api.deps import admin_user, audit, current_user
from app.api.searches import _uuid, ai_http_error, ai_rate
from app.api.serializers import match_out
from app.core.config import get_settings
from app.core.db import get_db, utcnow
from app.core.ratelimit import TELEGRAM_LINK, get_limiter
from app.core.security import new_token, token_hash
from app.models import (
    AIUsage,
    Analysis,
    ChatMessage,
    ChatThread,
    Invite,
    Listing,
    Notification,
    SearchMatch,
    SearchProfile,
    SearchRun,
    TelegramLink,
    User,
)
from app.services import assistant, notify, resilience, telegram
from app.services.digest import send_digest
from app.sources.registry import all_sources

router = APIRouter(tags=["misc"])


# ---------------------------------------------------------------------- chat
@router.get("/api/chat/threads")
async def threads(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.scalars(
            select(ChatThread)
            .where(ChatThread.user_id == user.id)
            .order_by(ChatThread.updated_at.desc())
            .limit(50)
        )
    ).all()
    return [{"id": str(t.id), "title": t.title, "updated_at": t.updated_at.isoformat()} for t in rows]


async def _thread(db: AsyncSession, user: User, thread_id: str) -> ChatThread:
    t = await db.get(ChatThread, _uuid(thread_id))
    if t is None or t.user_id != user.id:
        raise HTTPException(404, "Not found")
    return t


def _msg_out(m: ChatMessage) -> dict:
    return {
        "id": str(m.id),
        "role": m.role,
        "content": m.content,
        "refs": m.refs or {},
        "created_at": m.created_at.isoformat(),
    }


@router.post("/api/chat/threads", status_code=201)
async def new_thread(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    t = ChatThread(user_id=user.id)
    db.add(t)
    await db.commit()
    return {"id": str(t.id), "title": t.title, "updated_at": t.updated_at.isoformat()}


@router.get("/api/chat/threads/{thread_id}")
async def thread_messages(
    thread_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    t = await _thread(db, user, thread_id)
    msgs = (
        await db.scalars(
            select(ChatMessage).where(ChatMessage.thread_id == t.id).order_by(ChatMessage.created_at)
        )
    ).all()
    return {"id": str(t.id), "title": t.title, "messages": [_msg_out(m) for m in msgs]}


@router.delete("/api/chat/threads/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    t = await _thread(db, user, thread_id)
    await db.delete(t)
    await db.commit()


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    focus: list[str] = Field(default_factory=list, max_length=6)


@router.post("/api/chat/threads/{thread_id}/messages")
async def send_message(
    thread_id: str, body: ChatIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    await ai_rate(user)
    t = await _thread(db, user, thread_id)
    focus: list[uuid.UUID] = []
    for f in body.focus:
        m = await db.get(SearchMatch, _uuid(f))
        if m is None or m.user_id != user.id:
            raise HTTPException(404, "Listing not found")
        focus.append(m.id)
    me = await db.get(User, user.id)
    assert me
    try:
        reply = await assistant.chat(db, me, t, body.text, focus)
    except (gateway.NoProvider, gateway.BudgetExceeded, ProviderError) as e:
        await db.rollback()
        raise ai_http_error(e) from e
    return _msg_out(reply)


# --------------------------------------------------------- notifications/telegram
@router.get("/api/notifications/telegram")
async def telegram_status(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    link = await db.scalar(select(TelegramLink).where(TelegramLink.user_id == user.id))
    return {
        "configured": telegram.configured(),
        "bot_username": get_settings().telegram_bot_username,
        "linked": bool(link and link.chat_id),
        "username": link.username if link else None,
        "linked_at": link.linked_at.isoformat() if link and link.linked_at else None,
    }


@router.post("/api/notifications/telegram/code")
async def telegram_code(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if not telegram.configured():
        raise HTTPException(409, "Telegram isn't configured on this server yet.")
    ok, retry = await get_limiter().hit(f"tg-link:{user.id}", TELEGRAM_LINK)
    if not ok:
        raise HTTPException(429, "Too many codes requested.", headers={"Retry-After": str(retry)})
    code = await notify.create_link_code(db, user)
    bot = get_settings().telegram_bot_username
    return {"code": code, "expires_in": 600, "deep_link": f"https://t.me/{bot}?start={code}" if bot else None}


@router.delete("/api/notifications/telegram", status_code=204)
async def telegram_unlink(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    link = await db.scalar(select(TelegramLink).where(TelegramLink.user_id == user.id))
    if link:
        await db.delete(link)
        await db.commit()


@router.post("/api/notifications/telegram/test")
async def telegram_test(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    link = await db.scalar(select(TelegramLink).where(TelegramLink.user_id == user.id))
    if not link or not link.chat_id:
        raise HTTPException(409, "Connect Telegram first.")
    try:
        await telegram.send_message(link.chat_id, "👋 Test from Schnäppli. Notifications are working.")
    except telegram.TelegramError as e:
        raise HTTPException(502, str(e)) from e
    return {"sent": True}


@router.post("/api/notifications/digest")
async def digest_now(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await ai_rate(user)
    result = await send_digest(db, user.id, "now", force=True)
    return {"result": result}


@router.get("/api/notifications")
async def history(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": str(n.id),
            "kind": n.kind,
            "title": n.title,
            "body": n.body,
            "status": n.status,
            "error": n.error,
            "match_id": str(n.match_id) if n.match_id else None,
            "created_at": n.created_at.isoformat(),
        }
        for n in rows
    ]


# -------------------------------------------------------------------- sources
@router.get("/api/sources/inbox")
async def inbox_info(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Where to forward Ricardo / tutti alert mails, and how the inbox is doing."""
    from app.services import inbox_import
    from app.sources import inbox

    s = get_settings()
    st = await inbox_import.status(db) if inbox.configured() else {}
    out = {
        "configured": inbox.configured(),
        "address": s.inbox_imap_user or None,
        "checked_at": st.get("checked_at"),
        "last_alert_at": st.get("last_alert_at"),
        "totals": st.get("totals", {}),
        "unrouted": st.get("unrouted", 0),
        "unreadable": st.get("unreadable", 0),
        "ok": st.get("error") is None if st else None,
    }
    if user.is_admin:
        out["error"] = st.get("error")
    return out


@router.get("/api/sources")
async def sources(user: User = Depends(current_user)):
    out = []
    for s in all_sources().values():
        st = s.status()
        out.append(
            {
                "id": s.id,
                "name": s.name,
                "kind": s.kind,
                "homepage": s.homepage,
                "state": st.state,
                "reason": st.reason,
                "alternatives": st.alternatives,
                "available": st.available,
            }
        )
    out.append(
        {
            "id": "link",
            "name": "Add by link",
            "kind": "mixed",
            "homepage": "",
            "state": "manual",
            "reason": "Paste a link to any listing. Read once, only where robots.txt allows.",
            "alternatives": None,
            "available": True,
        }
    )
    return out


# ------------------------------------------------------------------ dashboard
@router.get("/api/dashboard")
async def dashboard(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    me = await db.get(User, user.id)
    assert me
    since = utcnow() - timedelta(days=1)
    week = utcnow() - timedelta(days=7)
    active = await db.scalar(
        select(func.count())
        .select_from(SearchProfile)
        .where(SearchProfile.user_id == user.id, SearchProfile.status == "active")
    )
    new_today = await db.scalar(
        select(func.count())
        .select_from(SearchMatch)
        .where(
            SearchMatch.user_id == user.id,
            SearchMatch.first_seen_at >= since,
            SearchMatch.relevance != "irrelevant",
        )
    )
    good_week = await db.scalar(
        select(func.count())
        .select_from(SearchMatch)
        .where(
            SearchMatch.user_id == user.id,
            SearchMatch.first_seen_at >= week,
            SearchMatch.deal_label.in_(("exceptional", "good")),
        )
    )
    rows = (
        await db.execute(
            select(SearchMatch, Listing, SearchProfile, Analysis)
            .join(Listing, Listing.id == SearchMatch.listing_id)
            .join(SearchProfile, SearchProfile.id == SearchMatch.search_id)
            .outerjoin(Analysis, Analysis.id == SearchMatch.analysis_id)
            .where(
                SearchMatch.user_id == user.id,
                SearchMatch.status.not_in(("rejected",)),
                SearchMatch.deal_score.is_not(None),
                SearchMatch.first_seen_at >= week,
                SearchMatch.relevance != "irrelevant",
            )
            .order_by(SearchMatch.deal_score.desc())
            .limit(12)
        )
    ).all()
    drops = (
        await db.execute(
            select(SearchMatch, Listing, SearchProfile, Analysis)
            .join(Listing, Listing.id == SearchMatch.listing_id)
            .join(SearchProfile, SearchProfile.id == SearchMatch.search_id)
            .outerjoin(Analysis, Analysis.id == SearchMatch.analysis_id)
            .where(
                SearchMatch.user_id == user.id,
                SearchMatch.price_dropped_at >= week,
                SearchMatch.status != "rejected",
            )
            .order_by(SearchMatch.price_dropped_at.desc())
            .limit(6)
        )
    ).all()
    runs = (
        await db.execute(
            select(SearchRun, SearchProfile.title)
            .join(SearchProfile, SearchProfile.id == SearchRun.search_id)
            .where(SearchProfile.user_id == user.id)
            .order_by(SearchRun.started_at.desc())
            .limit(8)
        )
    ).all()
    next_run = await db.scalar(
        select(func.min(SearchProfile.next_run_at)).where(
            SearchProfile.user_id == user.id, SearchProfile.status == "active"
        )
    )
    budget = await gateway.budget_status(db, me)
    try:
        await gateway.resolve_credential(db, me)
        ai_ready = True
    except gateway.NoProvider:
        ai_ready = False
    link = await db.scalar(select(TelegramLink).where(TelegramLink.user_id == user.id))
    outage = await resilience.last_outage(db) if me.is_admin else None
    if outage and datetime.fromisoformat(outage["to"]) < utcnow() - timedelta(hours=48):
        outage = None
    return {
        "last_outage": outage,
        "active_searches": active or 0,
        "new_today": new_today or 0,
        "good_this_week": good_week or 0,
        "top": [match_out(m, listing, s, a) for m, listing, s, a in rows],
        "price_drops": [match_out(m, listing, s, a) for m, listing, s, a in drops],
        "recent_runs": [
            {
                "search": title,
                "status": r.status,
                "started_at": r.started_at.isoformat(),
                "new_matches": r.new_matches,
                "fetched": r.fetched,
                "error": r.error,
            }
            for r, title in runs
        ],
        "next_run_at": next_run.isoformat() if next_run else None,
        "ai_budget": budget,
        "setup": {
            "ai_ready": ai_ready,
            "telegram_linked": bool(link and link.chat_id),
            "telegram_configured": telegram.configured(),
            "location_set": me.lat is not None,
            "sources_ready": [s.id for s in all_sources().values() if s.status().available],
        },
    }


# ---------------------------------------------------------------------- admin
@router.get("/api/admin/users")
async def admin_users(admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    users = (await db.scalars(select(User).order_by(User.created_at))).all()
    month = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spend = dict(
        (
            await db.execute(
                select(AIUsage.user_id, func.sum(AIUsage.cost_usd))
                .where(AIUsage.created_at >= month)
                .group_by(AIUsage.user_id)
            )
        ).all()
    )
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "is_admin": u.is_admin,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat(),
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "ai_month_usd": float(spend.get(u.id) or 0),
        }
        for u in users
    ]


class AdminUserPatch(BaseModel):
    is_admin: bool | None = None
    is_active: bool | None = None


@router.patch("/api/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    body: AdminUserPatch,
    request: Request,
    admin: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db),
):
    u = await db.get(User, _uuid(user_id))
    if u is None:
        raise HTTPException(404, "Not found")
    if u.id == admin.id and (body.is_admin is False or body.is_active is False):
        raise HTTPException(409, "You can't remove your own admin rights or deactivate yourself.")
    if body.is_admin is not None:
        u.is_admin = body.is_admin
    if body.is_active is not None:
        u.is_active = body.is_active
    await audit(db, request, "admin_user_update", admin.id, f"{u.id}: {body.model_dump(exclude_none=True)}")
    await db.commit()
    return {"ok": True}


class InviteIn(BaseModel):
    note: str | None = Field(None, max_length=120)
    days: int = Field(7, ge=1, le=60)


@router.get("/api/admin/invites")
async def list_invites(admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Invite).order_by(Invite.created_at.desc()).limit(100))).all()
    return [
        {
            "id": str(i.id),
            "note": i.note,
            "expires_at": i.expires_at.isoformat(),
            "used": i.used_by is not None,
            "used_at": i.used_at.isoformat() if i.used_at else None,
        }
        for i in rows
    ]


@router.post("/api/admin/invites", status_code=201)
async def create_invite(
    body: InviteIn, request: Request, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)
):
    code = new_token(12)
    db.add(
        Invite(
            code_hash=token_hash(code),
            created_by=admin.id,
            note=body.note,
            expires_at=utcnow() + timedelta(days=body.days),
        )
    )
    await audit(db, request, "invite_created", admin.id, body.note)
    await db.commit()
    return {"code": code, "expires_in_days": body.days}


@router.delete("/api/admin/invites/{invite_id}", status_code=204)
async def delete_invite(
    invite_id: str, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)
):
    i = await db.get(Invite, _uuid(invite_id))
    if i:
        await db.delete(i)
        await db.commit()


@router.get("/api/admin/audit")
async def audit_log(admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    from app.models import AuditLog

    rows = (await db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200))).all()
    return [
        {
            "event": r.event,
            "user_id": str(r.user_id) if r.user_id else None,
            "ip": r.ip,
            "detail": r.detail,
            "at": r.created_at.isoformat(),
        }
        for r in rows
    ]
