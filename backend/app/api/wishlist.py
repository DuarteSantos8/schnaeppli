from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.searches import _uuid
from app.api.serializers import search_out, wishlist_out
from app.core.db import get_db, utcnow
from app.core.jobs import enqueue
from app.models import SearchProfile, User, WishlistItem

router = APIRouter(prefix="/api/wishlist", tags=["wishlist"])


class WishIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    parent_id: str | None = None
    kind: Literal["main", "accessory"] = "main"
    category: str | None = Field(None, max_length=80)
    essential: bool = False
    budget: float | None = Field(None, ge=0, le=10_000_000)
    compatibility: dict[str, str] = Field(default_factory=dict)
    status: Literal["planned", "interested", "purchased", "rejected"] = "planned"
    notes: str | None = Field(None, max_length=2000)
    sort: int = 0


class WishPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=160)
    category: str | None = Field(None, max_length=80)
    essential: bool | None = None
    budget: float | None = Field(None, ge=0, le=10_000_000)
    compatibility: dict[str, str] | None = None
    status: Literal["planned", "interested", "purchased", "rejected"] | None = None
    notes: str | None = Field(None, max_length=2000)
    sort: int | None = None


async def owned(db: AsyncSession, user: User, item_id: str) -> WishlistItem:
    w = await db.get(WishlistItem, _uuid(item_id))
    if w is None or w.user_id != user.id:
        raise HTTPException(404, "Not found")
    return w


def _clean_compat(c: dict[str, str]) -> dict[str, str]:
    if len(c) > 12:
        raise HTTPException(422, "Too many compatibility fields")
    return {str(k)[:40]: str(v)[:120] for k, v in c.items()}


@router.get("")
async def list_items(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    items = (
        await db.scalars(
            select(WishlistItem)
            .where(WishlistItem.user_id == user.id)
            .order_by(WishlistItem.sort, WishlistItem.created_at)
        )
    ).all()
    return [wishlist_out(w) for w in items]


@router.post("", status_code=201)
async def create_item(body: WishIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    parent = await owned(db, user, body.parent_id) if body.parent_id else None
    w = WishlistItem(
        user_id=user.id,
        title=body.title.strip(),
        parent_id=parent.id if parent else None,
        kind="accessory" if parent else body.kind,
        category=body.category,
        essential=body.essential,
        budget=Decimal(str(body.budget)) if body.budget is not None else None,
        compatibility=_clean_compat(body.compatibility),
        status=body.status,
        notes=body.notes,
        sort=body.sort,
    )
    if parent and not w.compatibility and parent.compatibility:
        w.compatibility = dict(parent.compatibility)  # inherit e.g. the camera mount
    db.add(w)
    await db.commit()
    return wishlist_out(w)


@router.patch("/{item_id}")
async def update_item(
    item_id: str, body: WishPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    w = await owned(db, user, item_id)
    data = body.model_dump(exclude_unset=True)
    if "budget" in data:
        data["budget"] = Decimal(str(data["budget"])) if data["budget"] is not None else None
    if data.get("compatibility") is not None:
        data["compatibility"] = _clean_compat(data["compatibility"])
    for k, v in data.items():
        setattr(w, k, v)
    await db.commit()
    return wishlist_out(w)


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    w = await owned(db, user, item_id)
    await db.delete(w)
    await db.commit()


@router.post("/{item_id}/search", status_code=201)
async def create_search_from_item(
    item_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Turn a wishlist item into a search (without AI: the user can refine it)."""
    w = await owned(db, user, item_id)
    if w.search_id:
        existing = await db.get(SearchProfile, w.search_id)
        if existing:
            return search_out(existing)
    parent_search = None
    if w.parent_id:
        parent = await db.get(WishlistItem, w.parent_id)
        parent_search = parent.search_id if parent else None
    compat = "; ".join(f"{k}: {v}" for k, v in (w.compatibility or {}).items())
    s = SearchProfile(
        user_id=user.id,
        title=w.title,
        prompt=w.notes or w.title,
        category=w.category,
        spec={
            "desired_products": [{"name": w.title}],
            "allow_alternatives": True,
            "queries": [w.title],
            "must_have": [f"compatible with {compat}"] if compat else [],
            "alternatives": [],
            "excluded": [],
            "preferred_brands": [],
            "accessories": [],
            "nice_to_have": [],
        },
        max_budget=w.budget,
        currency=user.currency,
        parent_search_id=parent_search,
        status="active",
        next_run_at=utcnow(),
    )
    db.add(s)
    await db.flush()
    w.search_id = s.id
    await db.commit()
    await enqueue("run_search_job", s.id)
    return search_out(s)
