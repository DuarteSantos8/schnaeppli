from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import gateway
from app.ai.providers import ProviderError
from app.api.deps import current_user
from app.api.searches import _uuid, ai_http_error, ai_rate, owned_search
from app.api.serializers import match_out
from app.core.db import get_db, utcnow
from app.models import Analysis, Listing, PricePoint, Purchase, SearchMatch, SearchProfile, User
from app.services import analysis as analysis_svc
from app.services import learning
from app.services import listings as listing_svc
from app.sources.base import SourceError
from app.sources.link import import_link

router = APIRouter(prefix="/api/deals", tags=["deals"])
STATUSES = ("new", "seen", "favorite", "interested", "planned", "purchased", "rejected")


async def owned_match(db: AsyncSession, user: User, match_id: str) -> SearchMatch:
    m = await db.get(SearchMatch, _uuid(match_id))
    if m is None or m.user_id != user.id:
        raise HTTPException(404, "Not found")
    return m


@router.get("")
async def feed(
    label: str | None = Query(None, pattern="^(exceptional|good|fair|overpriced|risky)$"),
    status: str | None = Query(None),
    search_id: str | None = None,
    min_score: int = Query(0, ge=0, le=100),
    days: int = Query(30, ge=1, le=365),
    sort: str = Query("score", pattern="^(score|newest|price|drop)$"),
    q: str | None = Query(None, max_length=100),
    limit: int = Query(40, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(SearchMatch, Listing, SearchProfile, Analysis)
        .join(Listing, Listing.id == SearchMatch.listing_id)
        .join(SearchProfile, SearchProfile.id == SearchMatch.search_id)
        .outerjoin(Analysis, Analysis.id == SearchMatch.analysis_id)
        .where(
            SearchMatch.user_id == user.id,
            SearchMatch.relevance != "irrelevant",
            SearchMatch.first_seen_at >= utcnow() - timedelta(days=days),
        )
    )
    if status:
        if status not in STATUSES:
            raise HTTPException(422, "Unknown status")
        query = query.where(SearchMatch.status == status)
    else:
        query = query.where(SearchMatch.status != "rejected")
    if label:
        query = query.where(SearchMatch.deal_label == label)
    if min_score:
        query = query.where(SearchMatch.deal_score >= min_score)
    if search_id:
        s = await owned_search(db, user, search_id)
        query = query.where(SearchMatch.search_id == s.id)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(Listing.title.ilike(like), SearchProfile.title.ilike(like)))
    if sort == "drop":
        query = query.where(SearchMatch.price_dropped_at.is_not(None))
    order = {
        "score": (SearchMatch.deal_score.desc().nulls_last(), SearchMatch.first_seen_at.desc()),
        "newest": (SearchMatch.first_seen_at.desc(),),
        "price": (SearchMatch.effective_price.asc().nulls_last(),),
        "drop": (SearchMatch.price_dropped_at.desc(),),
    }[sort]
    rows = (await db.execute(query.order_by(*order).limit(limit).offset(offset))).all()
    return [match_out(m, listing, s, a) for m, listing, s, a in rows]


@router.get("/{match_id}")
async def detail(match_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    m = await owned_match(db, user, match_id)
    listing = await db.get(Listing, m.listing_id)
    search = await db.get(SearchProfile, m.search_id)
    a = await db.get(Analysis, m.analysis_id) if m.analysis_id else None
    assert listing and search
    if m.status == "new":
        m.status = "seen"
        await db.commit()
    history = (
        await db.scalars(
            select(PricePoint).where(PricePoint.listing_id == listing.id).order_by(PricePoint.observed_at)
        )
    ).all()
    similar_rows = []
    product = (a.result or {}).get("identified_product") if a else None
    if product:
        rows = (
            await db.execute(
                select(SearchMatch, Listing, Analysis)
                .join(Listing, Listing.id == SearchMatch.listing_id)
                .join(Analysis, Analysis.id == SearchMatch.analysis_id)
                .where(
                    SearchMatch.user_id == user.id,
                    SearchMatch.id != m.id,
                    SearchMatch.relevance != "irrelevant",
                )
                .order_by(SearchMatch.deal_score.desc().nulls_last())
                .limit(60)
            )
        ).all()
        similar_rows = [
            r for r in rows if (r[2].result or {}).get("identified_product", "").lower() == product.lower()
        ][:6]
    out = match_out(m, listing, search, a, full=True)
    out["price_history"] = [
        {
            "price": float(p.price),
            "shipping": float(p.shipping_cost) if p.shipping_cost is not None else None,
            "at": p.observed_at.isoformat(),
        }
        for p in history
    ]
    out["similar"] = [match_out(sm, sl, None, sa) for sm, sl, sa in similar_rows]
    return out


class FeedbackIn(BaseModel):
    status: str
    note: str | None = Field(None, max_length=500)
    purchase_price: float | None = Field(None, ge=0, le=10_000_000)


@router.patch("/{match_id}")
async def feedback(
    match_id: str, body: FeedbackIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    if body.status not in STATUSES:
        raise HTTPException(422, "Unknown status")
    m = await owned_match(db, user, match_id)
    listing = await db.get(Listing, m.listing_id)
    search = await db.get(SearchProfile, m.search_id)
    a = await db.get(Analysis, m.analysis_id) if m.analysis_id else None
    me = await db.get(User, user.id)
    assert listing and search and me
    previous = m.status
    m.status = body.status
    m.feedback_at = utcnow()
    if body.note is not None:
        m.note = body.note
    if previous != body.status:
        learning.apply_feedback(me, m, listing, a, body.status)
    # Budget ledger: planned / interested / purchased mirror into the ledger. A
    # found listing is never counted as spent unless the user marks it purchased.
    existing = await db.scalar(select(Purchase).where(Purchase.match_id == m.id))
    if body.status in ("planned", "interested", "purchased"):
        amount = (
            Decimal(str(body.purchase_price))
            if body.purchase_price is not None
            else (m.effective_price or listing.price or Decimal(0))
        )
        if existing is None:
            existing = Purchase(
                user_id=user.id,
                title=listing.title[:200],
                amount=amount,
                currency=listing.currency,
                category=search.category,
                match_id=m.id,
                month=utcnow().strftime("%Y-%m"),
            )
            db.add(existing)
        existing.status = body.status
        existing.amount = amount
        if body.status == "purchased":
            existing.month = utcnow().strftime("%Y-%m")
    elif existing is not None and body.status == "rejected":
        existing.status = "rejected"
    await db.commit()
    return match_out(m, listing, search, a)


@router.post("/{match_id}/analyze")
async def deep_analysis(
    match_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    await ai_rate(user)
    m = await owned_match(db, user, match_id)
    try:
        result = await analysis_svc.analyze_match(db, m.id, deep=True)
    except (gateway.NoProvider, gateway.BudgetExceeded, ProviderError) as e:
        raise ai_http_error(e) from e
    if result and result.analysis_state == "limited":
        raise HTTPException(402, result.skip_reason or "AI budget limit reached")
    return await detail(match_id, user, db)


@router.post("/{match_id}/vision")
async def vision(match_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await ai_rate(user)
    m = await owned_match(db, user, match_id)
    if m.analysis_id is None:
        raise HTTPException(409, "Run the analysis first.")
    found = await analysis_svc.analyze_images(db, m.id)
    if found is None:
        raise HTTPException(
            409,
            "No photos could be analysed (none available, limit reached, or the model "
            "doesn't support images).",
        )
    return await detail(match_id, user, db)


class ImportIn(BaseModel):
    url: HttpUrl
    search_id: str


@router.post("/import", status_code=201)
async def import_by_link(
    body: ImportIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    await ai_rate(user)
    search = await owned_search(db, user, body.search_id)
    try:
        raw = await import_link(str(body.url))
    except SourceError as e:
        raise HTTPException(422, str(e)) from e
    listing, _new, prev = await listing_svc.upsert_listing(db, raw)
    me = await db.get(User, user.id)
    assert me
    m, created = await listing_svc.ensure_match(db, me, search, listing, prev)
    m.analysis_state, m.relevance, m.skip_reason = "queued", "pending", None
    await db.commit()
    try:
        await analysis_svc.analyze_match(db, m.id)
    except ProviderError:
        pass  # stays queued; the worker retries
    return await detail(str(m.id), user, db)
