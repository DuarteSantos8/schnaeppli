from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _clear_cookies
from app.api.deps import audit, current_user
from app.api.serializers import listing_out, search_out, wishlist_out
from app.core.db import get_db
from app.core.security import verify_password
from app.models import (
    AIUsage,
    ChatMessage,
    ChatThread,
    CustomShop,
    Listing,
    MailConnection,
    Notification,
    Purchase,
    SearchMatch,
    SearchProfile,
    Session,
    User,
    WishlistItem,
)
from app.schemas.user import ProfileUpdate, user_out
from app.services import geo, learning

router = APIRouter(prefix="/api/me", tags=["me"])


@router.patch("")
async def update_profile(
    body: ProfileUpdate, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    me = await db.get(User, user.id)
    assert me
    data = body.model_dump(exclude_unset=True)
    for key in ("notification_prefs", "search_schedule", "ai_limits", "ui_prefs"):
        if data.get(key) is not None:
            data[key] = getattr(body, key).model_dump()
    if "monthly_budget" in data:
        data["monthly_budget"] = (
            Decimal(str(data["monthly_budget"])) if data["monthly_budget"] is not None else None
        )
    for k, v in data.items():
        setattr(me, k, v)
    if "postal_code" in data or "city" in data or "country" in data:
        hit = None
        if (me.country or "CH") == "CH":
            hit = geo.lookup_postcode(me.postal_code) or geo.lookup_place(me.city)
        me.lat, me.lon = (hit[0], hit[1]) if hit else (None, None)
        if hit and not me.city:
            me.city = hit[2]
    if "ai_limits" in data and me.ai_paused_reason:
        me.ai_paused_reason = None  # user raised limits: resume, the gateway re-checks on the next call
    await db.commit()
    return user_out(me)


@router.post("/ai/resume")
async def resume_ai(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    me = await db.get(User, user.id)
    assert me
    me.ai_paused_reason = None
    await db.commit()
    return user_out(me)


@router.get("/learned")
async def learned(user: User = Depends(current_user)):
    return {"signals": (user.learned_prefs or {}).get("signals", 0), "items": learning.explain(user)}


@router.delete("/learned", status_code=204)
async def reset_learned(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    me = await db.get(User, user.id)
    assert me
    me.learned_prefs = {}
    await db.commit()


@router.get("/export")
async def export_data(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Everything Schnäppli stores about you, as JSON (secrets excluded)."""
    searches = (await db.scalars(select(SearchProfile).where(SearchProfile.user_id == user.id))).all()
    matches = (
        await db.execute(
            select(SearchMatch, Listing)
            .join(Listing, Listing.id == SearchMatch.listing_id)
            .where(SearchMatch.user_id == user.id)
        )
    ).all()
    wish = (await db.scalars(select(WishlistItem).where(WishlistItem.user_id == user.id))).all()
    shops = (await db.scalars(select(CustomShop).where(CustomShop.user_id == user.id))).all()
    mail = await db.scalar(select(MailConnection).where(MailConnection.user_id == user.id))
    purchases = (await db.scalars(select(Purchase).where(Purchase.user_id == user.id))).all()
    usage = (await db.scalars(select(AIUsage).where(AIUsage.user_id == user.id))).all()
    threads = (await db.scalars(select(ChatThread).where(ChatThread.user_id == user.id))).all()
    msgs = (
        (
            await db.scalars(select(ChatMessage).where(ChatMessage.thread_id.in_([t.id for t in threads])))
        ).all()
        if threads
        else []
    )
    return {
        "profile": user_out(user).model_dump(),
        "searches": [search_out(s) for s in searches],
        "matches": [
            {"status": m.status, "deal_score": m.deal_score, "note": m.note, "listing": listing_out(lst)}
            for m, lst in matches
        ],
        "wishlist": [wishlist_out(w) for w in wish],
        "shops": [
            {"name": s.name, "search_url": s.search_url, "kind": s.kind, "enabled": s.enabled} for s in shops
        ],
        "mailbox": (
            {
                "address": mail.username,
                "server": mail.imap_host,
                "folder": mail.folder,
                "enabled": mail.enabled,
            }
            if mail
            else None
        ),  # never the password
        "purchases": [
            {"title": p.title, "amount": float(p.amount), "status": p.status, "month": p.month}
            for p in purchases
        ],
        "ai_usage": [
            {
                "at": u.created_at.isoformat(),
                "kind": u.kind,
                "provider": u.provider,
                "model": u.model,
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "cost_usd": float(u.cost_usd),
            }
            for u in usage
        ],
        "chats": [
            {
                "title": t.title,
                "messages": [{"role": m.role, "content": m.content} for m in msgs if m.thread_id == t.id],
            }
            for t in threads
        ],
    }


class DeleteAccountIn(BaseModel):
    password: str = Field(max_length=256)
    confirm: str = Field(description="Must be the literal text DELETE")


@router.delete("", status_code=204)
async def delete_account(
    body: DeleteAccountIn,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    me = await db.get(User, user.id)
    assert me
    if body.confirm != "DELETE" or not verify_password(me.password_hash, body.password):
        raise HTTPException(403, "Password incorrect or confirmation missing.")
    if me.is_admin:
        others = (await db.scalars(select(User.id).where(User.is_admin.is_(True), User.id != me.id))).first()
        users = (await db.scalars(select(User.id).where(User.id != me.id))).first()
        if users and not others:
            raise HTTPException(
                409, "Make another user an administrator before deleting the last admin account."
            )
    await audit(db, request, "account_deleted", None, f"user {me.id}")
    # Cascades remove searches, matches, analyses, usage, credentials, chats, telegram link.
    await db.execute(delete(Session).where(Session.user_id == me.id))
    await db.execute(delete(Notification).where(Notification.user_id == me.id))
    await db.delete(me)
    await db.commit()
    _clear_cookies(response)
