from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.searches import _uuid
from app.core.db import get_db, utcnow
from app.models import Purchase, User, WishlistItem

router = APIRouter(prefix="/api/budget", tags=["budget"])
Status = Literal["planned", "interested", "purchased", "rejected"]


def _month(v: str | None) -> str:
    m = v or utcnow().strftime("%Y-%m")
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", m):
        raise HTTPException(422, "month must be YYYY-MM")
    return m


def purchase_out(p: Purchase) -> dict:
    return {
        "id": str(p.id),
        "title": p.title,
        "amount": float(p.amount),
        "currency": p.currency,
        "category": p.category,
        "status": p.status,
        "month": p.month,
        "match_id": str(p.match_id) if p.match_id else None,
        "note": p.note,
        "created_at": p.created_at.isoformat(),
    }


@router.get("")
async def summary(
    month: str | None = Query(None), user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    m = _month(month)
    items = (
        await db.scalars(
            select(Purchase)
            .where(Purchase.user_id == user.id, Purchase.month == m)
            .order_by(Purchase.created_at.desc())
        )
    ).all()
    totals = {"purchased": 0.0, "planned": 0.0, "interested": 0.0}
    by_cat: dict[str, float] = {}
    for p in items:
        if p.status in totals:
            totals[p.status] += float(p.amount)
        if p.status == "purchased":
            by_cat[p.category or "Other"] = by_cat.get(p.category or "Other", 0) + float(p.amount)
    wish_total = await db.scalar(
        select(func.coalesce(func.sum(WishlistItem.budget), 0)).where(
            WishlistItem.user_id == user.id, WishlistItem.status.in_(("planned", "interested"))
        )
    )
    budget = float(user.monthly_budget) if user.monthly_budget is not None else None
    months = (
        await db.execute(
            select(Purchase.month, func.sum(Purchase.amount))
            .where(Purchase.user_id == user.id, Purchase.status == "purchased")
            .group_by(Purchase.month)
            .order_by(Purchase.month.desc())
            .limit(12)
        )
    ).all()
    return {
        "month": m,
        "currency": user.currency,
        "monthly_budget": budget,
        "purchased": round(totals["purchased"], 2),
        "planned": round(totals["planned"], 2),
        "interested": round(totals["interested"], 2),
        "remaining": round(budget - totals["purchased"], 2) if budget is not None else None,
        "remaining_after_planned": round(budget - totals["purchased"] - totals["planned"], 2)
        if budget is not None
        else None,
        "by_category": [
            {"category": k, "amount": round(v, 2)} for k, v in sorted(by_cat.items(), key=lambda x: -x[1])
        ],
        "wishlist_planned": float(wish_total or 0),
        "history": [{"month": mo, "purchased": float(a or 0)} for mo, a in reversed(months)],
        "items": [purchase_out(p) for p in items],
    }


class PurchaseIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    amount: float = Field(ge=0, le=10_000_000)
    category: str | None = Field(None, max_length=80)
    status: Status = "planned"
    month: str | None = None
    note: str | None = Field(None, max_length=500)


class PurchasePatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    amount: float | None = Field(None, ge=0, le=10_000_000)
    category: str | None = Field(None, max_length=80)
    status: Status | None = None
    month: str | None = None
    note: str | None = Field(None, max_length=500)


@router.post("/items", status_code=201)
async def add_item(body: PurchaseIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = Purchase(
        user_id=user.id,
        title=body.title.strip(),
        amount=Decimal(str(body.amount)),
        currency=user.currency,
        category=body.category,
        status=body.status,
        month=_month(body.month),
        note=body.note,
    )
    db.add(p)
    await db.commit()
    return purchase_out(p)


@router.patch("/items/{item_id}")
async def update_item(
    item_id: str, body: PurchasePatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    p = await db.get(Purchase, _uuid(item_id))
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "Not found")
    data = body.model_dump(exclude_unset=True)
    if "amount" in data and data["amount"] is not None:
        data["amount"] = Decimal(str(data["amount"]))
    if "month" in data:
        data["month"] = _month(data["month"])
    for k, v in data.items():
        setattr(p, k, v)
    await db.commit()
    return purchase_out(p)


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(item_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Purchase, _uuid(item_id))
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "Not found")
    await db.delete(p)
    await db.commit()
