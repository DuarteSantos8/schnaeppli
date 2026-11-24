"""Notifications: deal alerts, price drops, usage warnings, search failures,
Telegram account linking. Every send is recorded in ``notifications`` with a
dedupe key so nothing is sent twice."""

from __future__ import annotations

import secrets
import string
from datetime import timedelta
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.security import token_hash
from app.models import Analysis, Listing, Notification, SearchMatch, SearchProfile, TelegramLink, User
from app.services import telegram
from app.services.telegram import esc

log = structlog.get_logger()
LABEL_TEXT = {
    "exceptional": "Exceptional deal",
    "good": "Good deal",
    "fair": "Fair price",
    "overpriced": "Overpriced",
    "risky": "Risky / not enough info",
}
CODE_ALPHABET = string.ascii_uppercase + string.digits


def money(amount: Decimal | float | None, currency: str) -> str:
    if amount is None:
        return "n/a"
    v = float(amount)
    s = f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"
    return f"{currency} {s.replace(',', '’')}"


async def _chat_id(db: AsyncSession, user_id) -> str | None:
    link = await db.scalar(select(TelegramLink).where(TelegramLink.user_id == user_id))
    return link.chat_id if link and link.chat_id else None


async def _already(db: AsyncSession, user_id, key: str) -> bool:
    return bool(
        await db.scalar(
            select(Notification.id).where(Notification.user_id == user_id, Notification.dedupe_key == key)
        )
    )


async def _record(
    db: AsyncSession,
    user_id,
    kind: str,
    title: str,
    body: str,
    *,
    key: str | None,
    match_id=None,
    status: str = "sent",
    error: str | None = None,
) -> None:
    db.add(
        Notification(
            user_id=user_id,
            kind=kind,
            title=title[:200],
            body=body,
            dedupe_key=key,
            match_id=match_id,
            status=status,
            error=error,
        )
    )


def app_link(path: str) -> str:
    return get_settings().public_url.rstrip("/") + path


def deal_caption(
    listing: Listing, match: SearchMatch, analysis: Analysis | None, search: SearchProfile
) -> str:
    mv = (analysis.market_value if analysis else {}) or {}
    parts = [
        f"<b>{esc(LABEL_TEXT.get(match.deal_label or '', 'New match'))} · {match.deal_score}/100</b>",
        esc(listing.title[:200]),
        "",
        f"💰 {esc(money(listing.price, listing.currency))}"
        + (
            f" + shipping {esc(money(listing.shipping_cost, listing.currency))}"
            if listing.shipping_cost
            else ""
        )
        + (" (shipping estimated)" if match.effective_price_estimated else ""),
    ]
    if mv.get("mid"):
        parts.append(
            f"📊 Est. market value {esc(money(mv['mid'], listing.currency))} · {esc(mv.get('source', ''))}"
        )
    parts.append(f"🛒 {esc(listing.source)} · for “{esc(search.title)}”")
    if match.distance_km is not None:
        parts.append(f"📍 ~{round(match.distance_km)} km (estimate)")
    summary = (analysis.result or {}).get("summary") if analysis else None
    if summary:
        parts += ["", f"<i>{esc(summary[:400])}</i>"]
    return "\n".join(parts)


def deal_buttons(listing: Listing, match: SearchMatch) -> list[list[dict]]:
    return [
        [
            {"text": "Open listing", "url": listing.url},
            {"text": "In Schnäppli", "url": app_link(f"/deals/{match.id}")},
        ]
    ]


async def maybe_alert_deal(db: AsyncSession, match: SearchMatch) -> bool:
    """Instant alert for exceptional (and optionally good) deals."""
    if match.deal_score is None or match.notified_at is not None or match.status == "rejected":
        return False
    user = await db.get(User, match.user_id)
    search = await db.get(SearchProfile, match.search_id)
    if not user or not search:
        return False
    prefs = user.notification_prefs or {}
    threshold = int((search.notify or {}).get("instant_min_score", 85))
    wants = (match.deal_label == "exceptional" and prefs.get("instant_exceptional", True)) or (
        match.deal_label == "good" and prefs.get("instant_good", False)
    )
    if not wants or match.deal_score < threshold and match.deal_label != "exceptional":
        return False
    key = f"deal:{match.id}"
    if await _already(db, user.id, key):
        return False
    chat = await _chat_id(db, user.id)
    listing = await db.get(Listing, match.listing_id)
    analysis = await db.get(Analysis, match.analysis_id) if match.analysis_id else None
    assert listing
    caption = deal_caption(listing, match, analysis, search)
    if not chat or not telegram.configured():
        await _record(
            db,
            user.id,
            "deal_alert",
            listing.title,
            caption,
            key=key,
            match_id=match.id,
            status="skipped",
            error="Telegram not linked",
        )
        match.notified_at = utcnow()
        await db.commit()
        return False
    try:
        if listing.images:
            await telegram.send_photo(chat, listing.images[0], caption, deal_buttons(listing, match))
        else:
            await telegram.send_message(chat, caption, deal_buttons(listing, match))
        await _record(db, user.id, "deal_alert", listing.title, caption, key=key, match_id=match.id)
    except telegram.TelegramError as e:
        await _record(
            db,
            user.id,
            "deal_alert",
            listing.title,
            caption,
            key=key,
            match_id=match.id,
            status="failed",
            error=str(e)[:300],
        )
    match.notified_at = utcnow()
    await db.commit()
    return True


async def maybe_alert_price_drop(db: AsyncSession, match: SearchMatch) -> bool:
    user = await db.get(User, match.user_id)
    if not user or not (user.notification_prefs or {}).get("price_drops", True):
        return False
    if match.price_dropped_at is None or match.previous_price is None or match.status == "rejected":
        return False
    if (match.deal_score or 0) < 50 and match.status not in ("favorite", "interested", "planned"):
        return False
    listing = await db.get(Listing, match.listing_id)
    search = await db.get(SearchProfile, match.search_id)
    if not listing or listing.price is None or not search:
        return False
    key = f"drop:{match.id}:{listing.price}"
    if await _already(db, user.id, key):
        return False
    text = (
        f"<b>Price drop · {match.deal_score}/100</b>\n{esc(listing.title[:200])}\n\n"
        f"{esc(money(match.previous_price, listing.currency))} → <b>{esc(money(listing.price, listing.currency))}</b>\n"
        f"for “{esc(search.title)}”"
    )
    chat = await _chat_id(db, user.id)
    status, err = "sent", None
    if chat and telegram.configured():
        try:
            await telegram.send_message(chat, text, deal_buttons(listing, match))
        except telegram.TelegramError as e:
            status, err = "failed", str(e)[:300]
    else:
        status, err = "skipped", "Telegram not linked"
    await _record(
        db, user.id, "price_drop", listing.title, text, key=key, match_id=match.id, status=status, error=err
    )
    await db.commit()
    return status == "sent"


async def queue_usage_warning(db: AsyncSession, user: User, period: str, spent: float, limit: float) -> None:
    if not (user.notification_prefs or {}).get("usage_warnings", True):
        return
    now = utcnow()
    key = f"usage:{period}:{now.strftime('%Y-%m' if period == 'month' else '%Y-%m-%d')}"
    if await _already(db, user.id, key):
        return
    pct = round(spent / limit * 100) if limit else 0
    text = (
        f"<b>AI budget: {pct}% of your {period}ly limit used</b>\n"
        f"${spent:.2f} of ${limit:.2f} (estimated from token usage). "
        f"Schnäppli pauses analysis at {(user.ai_limits or {}).get('pause_pct', 100)}%."
    )
    await _send_simple(db, user, "usage_warning", "AI budget warning", text, key)


async def notify_search_failure(db: AsyncSession, user: User, search: SearchProfile, error: str) -> None:
    if not (user.notification_prefs or {}).get("search_failures", True):
        return
    key = f"fail:{search.id}:{utcnow().strftime('%Y-%m-%d')}"
    if await _already(db, user.id, key):
        return
    text = f"<b>Search problem</b>\n“{esc(search.title)}”: {esc(error[:300])}"
    await _send_simple(db, user, "search_failure", "Search failed", text, key)


async def _send_simple(db: AsyncSession, user: User, kind: str, title: str, text: str, key: str) -> None:
    chat = await _chat_id(db, user.id)
    status, err = "sent", None
    if chat and telegram.configured():
        try:
            await telegram.send_message(chat, text)
        except telegram.TelegramError as e:
            status, err = "failed", str(e)[:300]
    else:
        status, err = "skipped", "Telegram not linked"
    await _record(db, user.id, kind, title, text, key=key, status=status, error=err)
    await db.commit()


# ------------------------------------------------------------- account linking
async def create_link_code(db: AsyncSession, user: User) -> str:
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    link = await db.scalar(select(TelegramLink).where(TelegramLink.user_id == user.id))
    if link is None:
        link = TelegramLink(user_id=user.id)
        db.add(link)
    link.code_hash = token_hash(code)
    link.code_expires_at = utcnow() + timedelta(minutes=10)
    await db.commit()
    return code


async def handle_update(db: AsyncSession, update: dict) -> None:
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    if chat.get("type") != "private":
        return
    chat_id = str(chat.get("id"))
    text = (msg.get("text") or "").strip()
    username = (msg.get("from") or {}).get("username")
    if text.startswith("/start"):
        code = text.removeprefix("/start").strip().upper()
        if not code:
            await telegram.send_message(
                chat_id,
                "Hi! To connect this chat, open Schnäppli → Settings → Notifications "
                "and tap <b>Connect Telegram</b>.",
            )
            return
        link = await db.scalar(select(TelegramLink).where(TelegramLink.code_hash == token_hash(code)))
        if link is None or link.code_expires_at is None or link.code_expires_at < utcnow():
            await telegram.send_message(
                chat_id, "This code is invalid or expired. Create a new one in Schnäppli."
            )
            return
        # One chat belongs to one account.
        others = (await db.scalars(select(TelegramLink).where(TelegramLink.chat_id == chat_id))).all()
        for o in others:
            if o.user_id != link.user_id:
                o.chat_id = None
                o.linked_at = None
        link.chat_id, link.username, link.linked_at = chat_id, username, utcnow()
        link.code_hash, link.code_expires_at = None, None
        await db.commit()
        await telegram.send_message(
            chat_id, "✅ Connected. You'll get deal alerts and digests here. Send /stop to disconnect."
        )
    elif text == "/stop":
        links = (await db.scalars(select(TelegramLink).where(TelegramLink.chat_id == chat_id))).all()
        for link in links:
            link.chat_id, link.linked_at = None, None
        await db.commit()
        await telegram.send_message(chat_id, "Disconnected. You won't receive messages from Schnäppli anymore.")
    elif text in ("/help", "help"):
        await telegram.send_message(
            chat_id, "Schnäppli sends deal alerts and digests. /stop disconnects this chat."
        )
