"""Prompt interpretation (search creation) and the shopping chat."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import gateway
from app.ai.prompts import CHAT_SYSTEM, INTERPRET_SYSTEM, fence
from app.ai.providers import Prompt
from app.core.db import utcnow
from app.models import Analysis, ChatMessage, ChatThread, Listing, Purchase, SearchMatch, SearchProfile, User
from app.schemas.search import InterpretationResult


async def interpret(db: AsyncSession, user: User, turns: list[dict]) -> InterpretationResult:
    """``turns``: alternating user messages and the assistant's earlier questions."""
    convo = []
    for t in turns[-10:]:
        who = "User" if t.get("role") == "user" else "Your earlier question(s)"
        convo.append(f"{who}: {fence(t.get('content', ''), 3000)}")
    context = (
        f"User currency: {user.currency}. "
        f"Default delivery preference: {user.delivery}. Default pickup radius: {user.radius_km} km. "
        "Location: Switzerland (precise location intentionally not shared)."
    )
    prompt = Prompt(system=INTERPRET_SYSTEM, user=context + "\n\n" + "\n".join(convo), max_tokens=3000)
    completion, _ = await gateway.call(db, user, "prompt_interpretation", prompt, InterpretationResult)
    result: InterpretationResult = completion.parsed
    if not result.draft.currency:
        result.draft.currency = user.currency
    return result


async def _month_budget(db: AsyncSession, user: User) -> dict:
    month = utcnow().strftime("%Y-%m")
    rows = (
        await db.execute(
            select(Purchase.status, func.sum(Purchase.amount))
            .where(Purchase.user_id == user.id, Purchase.month == month)
            .group_by(Purchase.status)
        )
    ).all()
    by = {s: float(a or 0) for s, a in rows}
    total = float(user.monthly_budget) if user.monthly_budget is not None else None
    return {
        "budget": total,
        "purchased": by.get("purchased", 0.0),
        "planned": by.get("planned", 0.0),
        "remaining": (total - by.get("purchased", 0.0)) if total is not None else None,
    }


async def build_context(db: AsyncSession, user: User, focus_match_ids: list[uuid.UUID]) -> tuple[str, dict]:
    searches = (
        await db.scalars(
            select(SearchProfile)
            .where(SearchProfile.user_id == user.id, SearchProfile.status == "active")
            .limit(20)
        )
    ).all()
    lines = ["USER'S ACTIVE SEARCHES:"]
    for s in searches:
        lines.append(f"- {s.title} (budget {s.currency} {s.max_budget or 'none'}, condition {s.condition})")
    b = await _month_budget(db, user)
    lines.append(f"\nMONTHLY BUDGET ({user.currency}): {b}")

    q = (
        select(SearchMatch, Listing, Analysis, SearchProfile)
        .join(Listing, Listing.id == SearchMatch.listing_id)
        .join(SearchProfile, SearchProfile.id == SearchMatch.search_id)
        .outerjoin(Analysis, Analysis.id == SearchMatch.analysis_id)
        .where(SearchMatch.user_id == user.id)
    )
    focus = (await db.execute(q.where(SearchMatch.id.in_(focus_match_ids)))).all() if focus_match_ids else []
    top = (
        await db.execute(
            q.where(SearchMatch.deal_score.is_not(None), SearchMatch.status != "rejected")
            .order_by(SearchMatch.deal_score.desc())
            .limit(15)
        )
    ).all()
    refs: dict[str, str] = {}
    seen = set()
    lines.append("\nLISTINGS (ref, search, score, label, effective price, est. market value):")
    for i, (m, listing, a, s) in enumerate(list(focus) + list(top)):
        if m.id in seen:
            continue
        seen.add(m.id)
        ref = f"L{i + 1}"
        refs[ref] = str(m.id)
        mv = (a.market_value or {}) if a else {}
        res = (a.result or {}) if a else {}
        lines.append(
            f"[{ref}]{' (FOCUS)' if m.id in focus_match_ids else ''} search='{s.title}' score={m.deal_score} "
            f"label={m.deal_label} price={listing.currency} {m.effective_price}"
            f"{' (shipping estimated)' if m.effective_price_estimated else ''} market≈{mv.get('mid')} "
            f"({mv.get('source')}) status={m.status}\n"
            f"<untrusted_listing>title: {fence(listing.title, 200)} | condition: {res.get('condition')} | "
            f"facts: {fence('; '.join(res.get('facts', [])[:6]), 600)} | "
            f"AI assumptions: {fence('; '.join(res.get('assumptions', [])[:4]), 400)}</untrusted_listing>"
        )
    return "\n".join(lines), refs


async def chat(
    db: AsyncSession, user: User, thread: ChatThread, text: str, focus_match_ids: list[uuid.UUID]
) -> ChatMessage:
    history_rows = (
        await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(12)
        )
    ).all()
    history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]
    context, refs = await build_context(db, user, focus_match_ids)
    db.add(ChatMessage(thread_id=thread.id, role="user", content=text))
    await db.flush()
    prompt = Prompt(
        system=CHAT_SYSTEM,  # stable, so it stays prompt-cached
        user="DATA (read-only, current as of now):\n" + context + "\n\nUSER QUESTION:\n" + fence(text, 4000),
        history=history,
        max_tokens=2500,
    )
    completion, _ = await gateway.call(db, user, "chat", prompt)
    reply = ChatMessage(thread_id=thread.id, role="assistant", content=completion.text.strip(), refs=refs)
    db.add(reply)
    if thread.title == "New conversation":
        thread.title = text.strip()[:60] or thread.title
    thread.updated_at = utcnow()
    await db.commit()
    return reply
