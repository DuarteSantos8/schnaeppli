"""Your own shops: added once, searched with every search."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.searches import _uuid
from app.core.db import get_db, utcnow
from app.models import CustomShop, User
from app.sources import shops as svc
from app.sources.base import SourceError

router = APIRouter(prefix="/api/shops", tags=["shops"])
MAX_SHOPS = 25


class ShopIn(BaseModel):
    address: str = Field(min_length=4, max_length=1000)
    name: str | None = Field(None, max_length=60)
    kind: Literal["retail", "secondhand"] = "retail"
    test_query: str | None = Field(None, max_length=100)


class ShopPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    enabled: bool | None = None
    kind: Literal["retail", "secondhand"] | None = None


class TestIn(BaseModel):
    query: str | None = Field(None, max_length=100)


def shop_out(s: CustomShop) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "host": s.host,
        "mode": s.mode,
        "search_url": s.search_url,
        "kind": s.kind,
        "enabled": s.enabled,
        "state": s.state,
        "state_text": s.state_detail or svc.STATE_TEXT.get(s.state, ""),
        "checked_at": s.checked_at.isoformat() if s.checked_at else None,
        "paused_until": s.paused_until.isoformat() if s.paused_until else None,
        "found_total": s.found_total,
    }


async def _owned(db: AsyncSession, user: User, shop_id: str) -> CustomShop:
    s = await db.get(CustomShop, _uuid(shop_id))
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "Not found")
    return s


async def _test(shop: CustomShop, query: str) -> list[dict]:
    """Run one real search on the shop and store the verdict."""
    now = utcnow()
    preview: list[dict] = []
    try:
        items = await svc.fetch_items(shop.mode, shop.search_url, query)
    except svc.ShopBlocked as e:
        shop.state, shop.state_detail, shop.paused_until = e.state, str(e)[:300], None
    except SourceError as e:
        shop.state, shop.state_detail = "error", str(e)[:300]
    else:
        if items:
            shop.state, shop.state_detail = "ok", None
        else:
            shop.state, shop.state_detail = (
                "ok",
                f"Readable, but nothing came up for “{query}”. Try another word.",
            )
        shop.paused_until = None
        preview = [
            {"title": i.title, "price": float(i.price) if i.price is not None else None,
             "currency": i.currency or "CHF", "url": i.url, "image": i.image}
            for i in items[:6]
        ]  # fmt: skip
    shop.checked_at = now
    return preview


@router.get("")
async def list_shops(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.scalars(
            select(CustomShop).where(CustomShop.user_id == user.id).order_by(CustomShop.created_at)
        )
    ).all()
    return [shop_out(s) for s in rows]


@router.post("", status_code=201)
async def add_shop(body: ShopIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        tpl = svc.template_from(body.address)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    host = svc.host_of(tpl.url)
    if why := svc.handled_reason(host):
        raise HTTPException(422, why)
    count = await db.scalar(select(func.count()).select_from(CustomShop).where(CustomShop.user_id == user.id))
    if (count or 0) >= MAX_SHOPS:
        raise HTTPException(422, f"You can add up to {MAX_SHOPS} shops.")
    if await db.scalar(select(CustomShop.id).where(CustomShop.user_id == user.id, CustomShop.host == host)):
        raise HTTPException(409, "This shop is already in your list.")
    name = (body.name or "").strip() or host.split(".")[0].replace("-", " ").title()
    shop = CustomShop(
        user_id=user.id, name=name[:60], host=host[:120], mode=tpl.mode, search_url=tpl.url, kind=body.kind
    )
    db.add(shop)
    preview = await _test(shop, (body.test_query or tpl.example or "usb").strip() or "usb")
    await db.commit()
    return {"shop": shop_out(shop), "preview": preview}


@router.post("/{shop_id}/test")
async def test_shop(
    shop_id: str, body: TestIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    shop = await _owned(db, user, shop_id)
    preview = await _test(shop, (body.query or "usb").strip() or "usb")
    await db.commit()
    return {"shop": shop_out(shop), "preview": preview}


@router.patch("/{shop_id}")
async def patch_shop(
    shop_id: str, body: ShopPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    shop = await _owned(db, user, shop_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(shop, k, v.strip() if isinstance(v, str) else v)
    await db.commit()
    return shop_out(shop)


@router.delete("/{shop_id}", status_code=204)
async def delete_shop(shop_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    shop = await _owned(db, user, shop_id)
    await db.delete(shop)
    await db.commit()
