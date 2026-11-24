from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import gateway
from app.ai.providers import ProviderError
from app.api.deps import current_user
from app.api.images import proxied
from app.api.serializers import match_out, run_out, search_out
from app.core.db import get_db, utcnow
from app.core.jobs import enqueue
from app.core.ratelimit import AI_PER_USER, get_limiter
from app.models import Analysis, Listing, SearchMatch, SearchProfile, SearchRun, User
from app.schemas.search import InterpretationResult, SearchIn, SearchPatch
from app.services import assistant
from app.services.schedule import next_search_run
from app.sources.registry import get_source

router = APIRouter(prefix="/api/searches", tags=["searches"])


def _uuid(v: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError as e:
        raise HTTPException(404, "Not found") from e


async def owned_search(db: AsyncSession, user: User, search_id: str) -> SearchProfile:
    s = await db.get(SearchProfile, _uuid(search_id))
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "Search not found")  # same answer for "not yours" and "missing"
    return s


async def ai_rate(user: User) -> None:
    ok, retry = await get_limiter().hit(f"ai:{user.id}", AI_PER_USER)
    if not ok:
        raise HTTPException(429, "Slow down a little.", headers={"Retry-After": str(retry)})


def ai_http_error(e: Exception) -> HTTPException:
    if isinstance(e, gateway.NoProvider):
        return HTTPException(409, str(e))
    if isinstance(e, gateway.BudgetExceeded):
        return HTTPException(402, str(e))
    if isinstance(e, ProviderError):
        return HTTPException(502, str(e))
    return HTTPException(500, "AI request failed")


def _validate_sources(sources: dict) -> dict:
    clean = {}
    for sid, cfg in (sources or {}).items():
        if get_source(sid) is None:
            raise HTTPException(422, f"Unknown source {sid!r}")
        clean[sid] = {"enabled": bool(cfg.get("enabled", True)), "priority": int(cfg.get("priority", 5))}
    return clean


def _validate_schedule(schedule: dict) -> dict:
    import re

    mode = schedule.get("mode", "default")
    if mode == "default":
        return {"mode": "default"}
    if mode == "interval":
        return {"mode": "interval", "hours": max(1, min(48, int(schedule.get("hours", 6))))}
    if mode == "custom":
        times = [t for t in schedule.get("times", []) if re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(t))]
        if not times:
            raise HTTPException(422, "Custom schedule needs at least one HH:MM time")
        return {"mode": "custom", "times": sorted(set(times))[:12]}
    raise HTTPException(422, "schedule.mode must be default, custom or interval")


class InterpretIn(BaseModel):
    turns: list[dict] = Field(min_length=1, max_length=12)


@router.post("/interpret", response_model=InterpretationResult)
async def interpret(
    body: InterpretIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    await ai_rate(user)
    for t in body.turns:
        if t.get("role") not in ("user", "assistant") or not isinstance(t.get("content"), str):
            raise HTTPException(422, "Each turn needs role user|assistant and text content")
        if len(t["content"]) > 4000:
            raise HTTPException(422, "Message too long")
    try:
        return await assistant.interpret(db, user, body.turns)
    except (gateway.NoProvider, gateway.BudgetExceeded, ProviderError) as e:
        raise ai_http_error(e) from e


async def _stats(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                SearchMatch.search_id,
                func.count(),
                func.max(SearchMatch.deal_score),
                func.sum(case((SearchMatch.status == "new", 1), else_=0)),
            )
            .where(SearchMatch.search_id.in_(ids), SearchMatch.relevance != "irrelevant")
            .group_by(SearchMatch.search_id)
        )
    ).all()
    good = dict(
        (
            await db.execute(
                select(SearchMatch.search_id, func.count())
                .where(
                    SearchMatch.search_id.in_(ids),
                    SearchMatch.deal_label.in_(("exceptional", "good")),
                    SearchMatch.status != "rejected",
                )
                .group_by(SearchMatch.search_id)
            )
        ).all()
    )
    out = {}
    for sid, total, best, new in rows:
        out[sid] = {
            "matches": total,
            "best_score": best,
            "new": int(new or 0),
            "good_deals": good.get(sid, 0),
        }
    return out


@router.get("")
async def list_searches(
    status: str | None = Query(None, pattern="^(active|paused|archived|completed)$"),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(SearchProfile).where(SearchProfile.user_id == user.id)
    if status:
        q = q.where(SearchProfile.status == status)
    searches = (await db.scalars(q.order_by(SearchProfile.priority, SearchProfile.updated_at.desc()))).all()
    stats = await _stats(db, [s.id for s in searches])
    # Hero image: the best-scoring match's photo.
    images = {}
    for s in searches:
        row = (
            await db.execute(
                select(Listing.images)
                .join(SearchMatch, SearchMatch.listing_id == Listing.id)
                .where(SearchMatch.search_id == s.id, SearchMatch.deal_score.is_not(None))
                .order_by(SearchMatch.deal_score.desc())
                .limit(1)
            )
        ).first()
        images[s.id] = proxied((row[0] or [None])[0]) if row else None
    return [search_out(s, stats.get(s.id, {}) | {"image": images.get(s.id)}) for s in searches]


@router.post("", status_code=201)
async def create_search(
    body: SearchIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    count = await db.scalar(
        select(func.count()).select_from(SearchProfile).where(SearchProfile.user_id == user.id)
    )
    if (count or 0) >= 200:
        raise HTTPException(409, "You've reached the limit of 200 searches.")
    parent = None
    if body.parent_search_id:
        parent = await owned_search(db, user, body.parent_search_id)
    s = SearchProfile(
        user_id=user.id,
        title=body.title.strip(),
        prompt=body.prompt,
        category=body.category,
        spec=body.spec.model_dump(),
        max_budget=Decimal(str(body.max_budget)) if body.max_budget is not None else None,
        currency=body.currency,
        condition=body.condition,
        prefer_condition=body.prefer_condition,
        postal_code=body.postal_code,
        radius_km=body.radius_km,
        delivery=body.delivery,
        sources=_validate_sources(body.sources),
        schedule=_validate_schedule(body.schedule),
        notify={
            "instant_min_score": int(body.notify.get("instant_min_score", 85)),
            "digest": bool(body.notify.get("digest", True)),
        },
        priority=body.priority,
        status=body.status,
        min_score=body.min_score,
        parent_search_id=parent.id if parent else None,
    )
    db.add(s)
    await db.flush()
    # First run right away, then follow the schedule.
    s.next_run_at = utcnow() if s.status == "active" else None
    await db.commit()
    if s.status == "active":
        await enqueue("run_search_job", s.id, job_id=f"run:{s.id}:{utcnow():%Y%m%d%H%M}")
    return search_out(s)


@router.get("/{search_id}")
async def get_search(search_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    s = await owned_search(db, user, search_id)
    stats = (await _stats(db, [s.id])).get(s.id, {})
    return search_out(s, stats)


@router.patch("/{search_id}")
async def update_search(
    search_id: str, body: SearchPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    s = await owned_search(db, user, search_id)
    data = body.model_dump(exclude_unset=True)
    if "spec" in data and data["spec"] is not None:
        data["spec"] = body.spec.model_dump() if body.spec else {}
    if "sources" in data and data["sources"] is not None:
        data["sources"] = _validate_sources(data["sources"])
    if "schedule" in data and data["schedule"] is not None:
        data["schedule"] = _validate_schedule(data["schedule"])
    if "max_budget" in data:
        data["max_budget"] = Decimal(str(data["max_budget"])) if data["max_budget"] is not None else None
    for k, v in data.items():
        setattr(s, k, v)
    s.next_run_at = next_search_run(s, user, utcnow())
    if s.status == "active" and s.last_run_at is None:
        s.next_run_at = utcnow()
    await db.commit()
    return search_out(s)


@router.post("/{search_id}/duplicate", status_code=201)
async def duplicate_search(
    search_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    s = await owned_search(db, user, search_id)
    copy = SearchProfile(
        user_id=user.id,
        title=f"{s.title} (copy)"[:120],
        prompt=s.prompt,
        category=s.category,
        spec=s.spec,
        max_budget=s.max_budget,
        currency=s.currency,
        condition=s.condition,
        prefer_condition=s.prefer_condition,
        postal_code=s.postal_code,
        radius_km=s.radius_km,
        delivery=s.delivery,
        sources=s.sources,
        schedule=s.schedule,
        notify=s.notify,
        priority=s.priority,
        status="paused",
        min_score=s.min_score,
    )
    db.add(copy)
    await db.commit()
    return search_out(copy)


@router.delete("/{search_id}", status_code=204)
async def delete_search(
    search_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    s = await owned_search(db, user, search_id)
    await db.delete(s)
    await db.commit()


@router.post("/{search_id}/run", status_code=202)
async def run_now(search_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    s = await owned_search(db, user, search_id)
    if s.status != "active":
        raise HTTPException(409, "Resume the search before running it.")
    if s.last_run_at and (utcnow() - s.last_run_at).total_seconds() < 120:
        raise HTTPException(429, "This search just ran. Try again in a couple of minutes.")
    await enqueue("run_search_job", s.id, job_id=f"run:{s.id}:{utcnow():%Y%m%d%H%M}")
    return {"queued": True}


@router.get("/{search_id}/runs")
async def search_runs(search_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    s = await owned_search(db, user, search_id)
    runs = (
        await db.scalars(
            select(SearchRun)
            .where(SearchRun.search_id == s.id)
            .order_by(SearchRun.started_at.desc())
            .limit(30)
        )
    ).all()
    return [run_out(r) for r in runs]


@router.get("/{search_id}/matches")
async def search_matches(
    search_id: str,
    include_irrelevant: bool = False,
    status: str | None = None,
    sort: str = Query("score", pattern="^(score|newest|price)$"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    s = await owned_search(db, user, search_id)
    q = (
        select(SearchMatch, Listing, Analysis)
        .join(Listing, Listing.id == SearchMatch.listing_id)
        .outerjoin(Analysis, Analysis.id == SearchMatch.analysis_id)
        .where(SearchMatch.search_id == s.id)
    )
    if not include_irrelevant:
        q = q.where(SearchMatch.relevance != "irrelevant")
    if status:
        q = q.where(SearchMatch.status == status)
    else:
        q = q.where(SearchMatch.status != "rejected")
    order = {
        "score": (SearchMatch.deal_score.desc().nulls_last(), SearchMatch.first_seen_at.desc()),
        "newest": (SearchMatch.first_seen_at.desc(),),
        "price": (SearchMatch.effective_price.asc().nulls_last(),),
    }[sort]
    rows = (await db.execute(q.order_by(*order).limit(limit).offset(offset))).all()
    return [match_out(m, listing, s, a) for m, listing, a in rows]
