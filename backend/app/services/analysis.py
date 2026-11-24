"""AI evaluation of matches. Separate from search runs and digests.

Cost control:
* An assessment is keyed by a hash of the listing *content* (not its price) and the
  search spec. A price change only rescores, it doesn't call the AI again.
* Photos are analysed only for promising listings, within daily limits.
* Every call goes through ``ai.gateway`` which enforces the user's budget.
"""

from __future__ import annotations

import hashlib
import json
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import gateway
from app.ai.prompts import (
    ANALYSIS_SYSTEM,
    VISION_SYSTEM,
    ListingAssessment,
    VisionFindings,
    fence,
)
from app.ai.providers import ImageInput, Prompt, ProviderError
from app.core.safe_http import fetch_image
from app.models import Analysis, Listing, SearchMatch, SearchProfile, User
from app.services import learning, scoring

log = structlog.get_logger()


def assessment_hash(listing: Listing, search: SearchProfile, kind: str) -> str:
    h = hashlib.sha256()
    payload = {
        "kind": kind,
        "title": listing.title,
        "desc": listing.description or "",
        "cond": listing.condition_text or listing.condition or "",
        "images": listing.images[:3],
        "spec": search.spec,
        "cond_pref": search.condition,
        "cur": search.currency,
        "v": 1,
    }
    h.update(json.dumps(payload, sort_keys=True, default=str).encode())
    return h.hexdigest()


def search_context(search: SearchProfile) -> str:
    spec = search.spec or {}
    lines = [f"Search: {search.title}"]
    if search.prompt:
        lines.append(f"User's own words: {fence(search.prompt, 1500)}")
    if spec.get("desired_products"):
        lines.append("Wanted: " + "; ".join(p["name"] for p in spec["desired_products"]))
    if spec.get("allow_alternatives", True) and spec.get("alternatives"):
        lines.append("Acceptable alternatives: " + "; ".join(p["name"] for p in spec["alternatives"]))
    elif not spec.get("allow_alternatives", True):
        lines.append("Alternatives: NOT wanted")
    for key, label in (
        ("excluded", "Exclude"),
        ("must_have", "Must have"),
        ("nice_to_have", "Nice to have"),
        ("preferred_brands", "Preferred brands"),
    ):
        if spec.get(key):
            lines.append(f"{label}: " + "; ".join(spec[key]))
    if spec.get("accessories"):
        lines.append(
            "Accessories wanted: "
            + "; ".join(
                a["name"] + (f" (compatible with {a['compatibility']})" if a.get("compatibility") else "")
                for a in spec["accessories"]
            )
        )
    if search.max_budget is not None:
        lines.append(f"Maximum budget: {search.currency} {search.max_budget}")
    lines.append(
        f"Condition wanted: {search.condition}"
        + (f", prefers {search.prefer_condition}" if search.prefer_condition else "")
    )
    return "\n".join(lines)


def listing_block(listing: Listing, match: SearchMatch, user: User) -> str:
    seller = listing.seller or {}
    parts = [
        f"Source: {listing.source}",
        f"Title: {fence(listing.title, 500)}",
        f"Asking price: {listing.currency} {listing.price}"
        if listing.price is not None
        else "Asking price: not given",
        f"Price type: {listing.price_type}",
        f"Shipping: {listing.currency} {listing.shipping_cost}"
        if listing.shipping_cost is not None
        else "Shipping cost: unknown",
        f"Stated condition: {fence(listing.condition_text or listing.condition or 'not stated', 200)}",
        f"Seller: feedback {seller.get('feedback_pct')}% from {seller.get('feedback_count')} ratings"
        if seller.get("feedback_count") is not None
        else "Seller info: none",
        f"Photos: {len(listing.images)}",
    ]
    if match.within_radius is not None:
        parts.append(
            f"Pickup distance: {'within' if match.within_radius else 'outside'} the user's radius "
            f"(~{round(match.distance_km or 0)} km)"
        )
    if user.share_location_with_ai and listing.location_text:
        parts.append(f"Listing location: {fence(listing.location_text, 100)}")
    parts.append(f"Description:\n{fence(listing.description or '(none)')}")
    return "<untrusted_listing>\n" + "\n".join(parts) + "\n</untrusted_listing>"


async def comparables(
    db: AsyncSession, search: SearchProfile, product: str | None, exclude: uuid.UUID
) -> list[float]:
    if not product:
        return []
    rows = (
        await db.execute(
            select(SearchMatch.effective_price, Analysis.result)
            .join(Analysis, Analysis.id == SearchMatch.analysis_id)
            .where(
                SearchMatch.search_id == search.id,
                SearchMatch.listing_id != exclude,
                SearchMatch.relevance.in_(("match", "bundle", "alternative")),
            )
            .limit(200)
        )
    ).all()
    key = product.strip().lower()
    return [
        float(p)
        for p, res in rows
        if p is not None and (res or {}).get("identified_product", "").strip().lower() == key
    ]


async def _images(listing: Listing, n: int = 3) -> list[ImageInput]:
    out = []
    for url in listing.images[:n]:
        got = await fetch_image(url)
        if got:
            out.append(ImageInput(data=got[0], media_type=got[1]))
    return out


async def rescore(
    db: AsyncSession,
    user: User,
    search: SearchProfile,
    match: SearchMatch,
    listing: Listing,
    analysis: Analysis,
    vision: dict | None = None,
) -> None:
    comps = await comparables(db, search, analysis.result.get("identified_product"), listing.id)
    delivery = search.delivery or user.delivery
    pickup_only = bool(listing.pickup_possible and listing.shipping_possible is False) or delivery == "pickup"
    res = scoring.score(
        analysis.result,
        match.effective_price,
        search.max_budget,
        comps,
        within_radius=match.within_radius,
        pickup_only=pickup_only,
        learned_adjustment=learning.adjustment(user, match, listing, analysis),
        vision=vision or (analysis.result.get("vision") if analysis.result else None),
    )
    analysis.score, analysis.label = res.score, res.label
    analysis.score_breakdown = {"items": res.breakdown}
    analysis.market_value = res.market
    match.deal_score, match.deal_label = res.score, res.label
    match.relevance = analysis.result.get("relevance", "match")
    match.analysis_id = analysis.id
    match.analysis_state = "done"
    match.price_at_analysis = listing.price


async def analyze_match(db: AsyncSession, match_id: uuid.UUID, *, deep: bool = False) -> SearchMatch | None:
    match = await db.get(SearchMatch, match_id)
    if match is None:
        return None
    listing = await db.get(Listing, match.listing_id)
    search = await db.get(SearchProfile, match.search_id)
    user = await db.get(User, match.user_id)
    if not (listing and search and user):
        return None
    kind = "deep_analysis" if deep else "quick_scan"
    ihash = assessment_hash(listing, search, kind)

    existing = await db.scalar(
        select(Analysis)
        .where(
            Analysis.user_id == user.id,
            Analysis.search_id == search.id,
            Analysis.listing_id == listing.id,
            Analysis.kind == kind,
            Analysis.input_hash == ihash,
        )
        .order_by(Analysis.created_at.desc())
    )
    if existing is not None:
        await rescore(db, user, search, match, listing, existing)
        await db.commit()
        return match

    prompt = Prompt(
        system=ANALYSIS_SYSTEM,
        user=(
            f"{search_context(search)}\n\nUser currency: {search.currency}\n\n"
            + listing_block(listing, match, user)
            + (
                "\n\nThis is a DEEP analysis: be thorough about compatibility, completeness, and value."
                if deep
                else ""
            )
        ),
        max_tokens=3000 if deep else 1800,
    )
    if deep:
        comps = await comparables(db, search, (listing.identity or {}).get("product"), listing.id)
        if comps:
            prompt.user += f"\n\nAsking prices of comparable listings Schnäppli has seen: {sorted(comps)[:20]}"
    try:
        completion, usage = await gateway.call(
            db, user, kind, prompt, ListingAssessment, search_id=search.id, listing_id=listing.id
        )
    except gateway.BudgetExceeded as e:
        match.analysis_state, match.skip_reason = "limited", str(e)[:200]
        await db.commit()
        return match
    except gateway.NoProvider as e:
        match.analysis_state, match.skip_reason = "limited", str(e)[:200]
        await db.commit()
        return match
    except ProviderError as e:
        match.analysis_state, match.skip_reason = ("queued" if e.retryable else "failed"), str(e)[:200]
        await db.commit()
        if e.retryable:
            raise
        return match

    result = completion.parsed.model_dump()
    analysis = Analysis(
        user_id=user.id,
        listing_id=listing.id,
        search_id=search.id,
        kind=kind,
        input_hash=ihash,
        provider=usage.provider,
        model=usage.model,
        result=result,
    )
    db.add(analysis)
    await db.flush()
    if result.get("identified_product"):
        listing.identity = {"product": result["identified_product"], "hash": listing.content_hash}
    await rescore(db, user, search, match, listing, analysis)
    await db.commit()

    # Photos: only for promising listings, and only once per content.
    promising = (match.deal_score or 0) >= 65 or result.get("worth_deep_look") or deep
    if listing.images and promising and match.relevance != "irrelevant":
        await analyze_images(db, match.id)
    return match


async def analyze_images(db: AsyncSession, match_id: uuid.UUID) -> dict | None:
    match = await db.get(SearchMatch, match_id)
    if match is None or match.analysis_id is None:
        return None
    analysis = await db.get(Analysis, match.analysis_id)
    listing = await db.get(Listing, match.listing_id)
    search = await db.get(SearchProfile, match.search_id)
    user = await db.get(User, match.user_id)
    if not (analysis and listing and search and user):
        return None
    if analysis.result.get("vision"):
        return analysis.result["vision"]
    images = await _images(listing)
    if not images:
        return None
    prompt = Prompt(
        system=VISION_SYSTEM,
        user=f"Listing title (untrusted): <untrusted_listing>{fence(listing.title, 300)}</untrusted_listing>\n"
        f"The buyer is looking for: {search.title}. {len(images)} photo(s) attached, index from 0.",
        images=images,
        max_tokens=1500,
    )
    try:
        completion, _ = await gateway.call(
            db,
            user,
            "vision_analysis",
            prompt,
            VisionFindings,
            search_id=search.id,
            listing_id=listing.id,
            require_vision=True,
        )
    except (gateway.BudgetExceeded, gateway.NoProvider, ProviderError) as e:
        log.info("vision_skipped", reason=str(e))
        return None
    vision = completion.parsed.model_dump()
    analysis.result = {**analysis.result, "vision": vision}
    await rescore(db, user, search, match, listing, analysis, vision)
    await db.commit()
    return vision
