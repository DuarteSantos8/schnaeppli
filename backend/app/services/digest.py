"""Daily digest: summarises *existing* analysis results. Never triggers new
listing analyses. Optional AI intro (one small call per digest)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import gateway
from app.ai.prompts import DIGEST_SYSTEM, DigestIntro, fence
from app.ai.providers import Prompt, ProviderError
from app.core.db import utcnow
from app.models import Analysis, Listing, SearchMatch, SearchProfile, TelegramLink, User
from app.services import telegram
from app.services.notify import LABEL_TEXT, _record, app_link, money
from app.services.telegram import esc

log = structlog.get_logger()


async def collect(db: AsyncSession, user: User) -> dict:
    prefs = user.notification_prefs or {}
    since = user.last_digest_at or (utcnow() - timedelta(days=1))
    min_score = int(prefs.get("digest_min_score", 60))
    max_n = int(prefs.get("digest_max_results", 8))
    rels = ["match", "bundle"]
    if prefs.get("digest_include_alternatives", True):
        rels.append("alternative")
    if prefs.get("digest_include_accessories", True):
        rels.append("accessory")

    base = (
        select(SearchMatch, Listing, SearchProfile, Analysis)
        .join(Listing, Listing.id == SearchMatch.listing_id)
        .join(SearchProfile, SearchProfile.id == SearchMatch.search_id)
        .outerjoin(Analysis, Analysis.id == SearchMatch.analysis_id)
        .where(
            SearchMatch.user_id == user.id,
            SearchMatch.status != "rejected",
            SearchProfile.status == "active",
            Listing.state == "active",
        )
    )
    new_rows = (
        await db.execute(
            base.where(
                SearchMatch.first_seen_at >= since,
                SearchMatch.analysis_state == "done",
                SearchMatch.relevance.in_(rels),
                SearchMatch.deal_score >= min_score,
            )
            .order_by(SearchMatch.deal_score.desc())
            .limit(max_n)
        )
    ).all()
    new_count = len(
        (
            await db.scalars(
                select(SearchMatch.id).where(
                    SearchMatch.user_id == user.id,
                    SearchMatch.first_seen_at >= since,
                    SearchMatch.relevance != "irrelevant",
                )
            )
        ).all()
    )
    drops = []
    if prefs.get("digest_include_price_drops", True):
        drops = (
            await db.execute(
                base.where(
                    SearchMatch.price_dropped_at >= since,
                    or_(
                        SearchMatch.deal_score >= min_score - 10,
                        SearchMatch.status.in_(("favorite", "interested")),
                    ),
                )
                .order_by(SearchMatch.price_dropped_at.desc())
                .limit(5)
            )
        ).all()
    expiring = (
        await db.execute(
            base.where(
                Listing.ends_at.is_not(None),
                Listing.ends_at <= utcnow() + timedelta(hours=24),
                Listing.ends_at > utcnow(),
                SearchMatch.deal_score >= min_score,
            )
            .order_by(Listing.ends_at)
            .limit(3)
        )
    ).all()

    savings = Decimal(0)
    for m, _l, _s, a in new_rows:
        mid = (a.market_value or {}).get("mid") if a else None
        if mid and m.effective_price is not None and Decimal(str(mid)) > m.effective_price:
            savings += Decimal(str(mid)) - m.effective_price
    return {
        "since": since,
        "new_count": new_count,
        "top": new_rows,
        "drops": drops,
        "expiring": expiring,
        "savings": savings,
    }


def _line(m: SearchMatch, listing: Listing) -> str:
    label = LABEL_TEXT.get(m.deal_label or "", "")
    return (
        f"• <b>{m.deal_score}</b> {esc(listing.title[:90])}\n"
        f"   {esc(money(m.effective_price, listing.currency))}"
        f"{' (est.)' if m.effective_price_estimated else ''} · {esc(listing.source)} · {esc(label)} · "
        f'<a href="{esc(listing.url)}">open</a>'
    )


async def ai_intro(db: AsyncSession, user: User, data: dict) -> str | None:
    if not data["top"] and not data["drops"]:
        return None
    rows = []
    for m, listing, s, a in data["top"][:6]:
        rows.append(
            f"- score {m.deal_score} ({m.deal_label}) · {listing.currency} {m.effective_price} · search "
            f"'{s.title}' · <untrusted_listing>{fence(listing.title, 150)}</untrusted_listing> · "
            f"{fence((a.result or {}).get('summary', '') if a else '', 200)}"
        )
    for m, listing, _s, _a in data["drops"][:3]:
        rows.append(
            f"- PRICE DROP {listing.currency} {m.previous_price} → {listing.price} · "
            f"<untrusted_listing>{fence(listing.title, 150)}</untrusted_listing>"
        )
    try:
        completion, _ = await gateway.call(
            db,
            user,
            "digest_generation",
            Prompt(
                system=DIGEST_SYSTEM,
                user=f"{data['new_count']} new listings. Results:\n" + "\n".join(rows),
                max_tokens=600,
            ),
            DigestIntro,
        )
        return completion.parsed.intro
    except (gateway.BudgetExceeded, gateway.NoProvider, ProviderError) as e:
        log.info("digest_intro_skipped", reason=str(e))
        return None


def render(user: User, data: dict, intro: str | None, slot: str) -> str | None:
    if not data["top"] and not data["drops"] and not data["expiring"]:
        if data["new_count"] == 0:
            return None  # nothing at all: don't send
        return (
            f"<b>Schnäppli · {esc(slot)}</b>\n{data['new_count']} new listing(s), none above your score threshold. "
            f"Nothing worth your time right now."
        )
    parts = [
        f"<b>Schnäppli digest · {esc(slot)}</b>",
        f"{data['new_count']} new listing(s) since the last digest.",
    ]
    if intro:
        parts += ["", esc(intro)]
    if data["top"]:
        parts += ["", "<b>Best offers</b>", *(_line(m, listing) for m, listing, _s, _a in data["top"])]
    if data["drops"]:
        parts += ["", "<b>Price drops</b>"]
        for m, listing, _s, _a in data["drops"]:
            parts.append(
                f"• {esc(listing.title[:80])}: {esc(money(m.previous_price, listing.currency))} → "
                f"<b>{esc(money(listing.price, listing.currency))}</b>"
            )
    if data["expiring"]:
        parts += ["", "<b>Ending soon</b>"]
        for m, listing, _s, _a in data["expiring"]:
            parts.append(
                f"• {esc(listing.title[:80])} · ends {listing.ends_at:%H:%M} UTC · score {m.deal_score}"
            )
    if data["savings"] > 0:
        parts += [
            "",
            f"Estimated savings vs. market value: {esc(money(data['savings'], user.currency))} "
            f"(based on estimates, not sold prices).",
        ]
    parts += ["", f'<a href="{esc(app_link("/"))}">Open Schnäppli</a>']
    return "\n".join(parts)


async def send_digest(db: AsyncSession, user_id, slot: str, *, force: bool = False) -> str:
    user = await db.get(User, user_id)
    if user is None:
        return "no user"
    data = await collect(db, user)
    intro = await ai_intro(db, user, data) if data["top"] else None
    text = render(user, data, intro, slot)
    user.last_digest_at = utcnow()
    if text is None and not force:
        await db.commit()
        return "nothing new"
    text = text or f"<b>Schnäppli · {esc(slot)}</b>\nNo new listings since the last digest."
    for m, *_ in data["top"]:
        m.digested_at = utcnow()
    link = await db.scalar(select(TelegramLink).where(TelegramLink.user_id == user.id))
    key = f"digest:{user.id}:{utcnow():%Y-%m-%d}:{slot}"
    if link and link.chat_id and telegram.configured():
        try:
            await telegram.send_message(link.chat_id, text)
            await _record(db, user.id, "digest", f"Digest {slot}", text, key=key)
            result = "sent"
        except telegram.TelegramError as e:
            await _record(
                db, user.id, "digest", f"Digest {slot}", text, key=key, status="failed", error=str(e)
            )
            result = "failed"
    else:
        await _record(
            db,
            user.id,
            "digest",
            f"Digest {slot}",
            text,
            key=key,
            status="skipped",
            error="Telegram not linked",
        )
        result = "stored (Telegram not linked)"
    await db.commit()
    return result
