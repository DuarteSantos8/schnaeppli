"""AI provider settings (BYOK + admin shared keys), connection tests, usage analytics."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import gateway
from app.ai.catalog import DEFAULT_MODEL, PROVIDERS, catalog
from app.ai.providers import Prompt, ProviderError, make_provider
from app.api.deps import admin_user, current_user
from app.api.searches import _uuid
from app.core.config import get_settings
from app.core.db import get_db, utcnow
from app.core.security import key_hint, secret_box
from app.models import AIUsage, AppSetting, ProviderCredential, SearchProfile, User

router = APIRouter(prefix="/api/ai", tags=["ai"])
KINDS = (
    "default",
    "prompt_interpretation",
    "quick_scan",
    "deep_analysis",
    "vision_analysis",
    "digest_generation",
    "chat",
)


def cred_out(c: ProviderCredential) -> dict:
    return {
        "id": str(c.id),
        "provider": c.provider,
        "label": c.label,
        "key_hint": c.key_hint,
        "base_url": c.base_url,
        "models": c.models or {},
        "shared": c.user_id is None,
        "shared_with_users": c.shared_with_users,
        "last_tested_at": c.last_tested_at.isoformat() if c.last_tested_at else None,
        "last_test_ok": c.last_test_ok,
        "last_test_error": c.last_test_error,
        "created_at": c.created_at.isoformat(),
    }


class CredentialIn(BaseModel):
    provider: Literal["anthropic", "openai", "gemini", "claude_code"]
    label: str = Field(min_length=1, max_length=80)
    api_key: str = Field(min_length=8, max_length=400)
    base_url: str | None = Field(None, max_length=300, pattern=r"^https?://[A-Za-z0-9.\-\[\]:]+(/.*)?$")
    models: dict[str, str] = Field(default_factory=dict)
    shared_with_users: bool = False  # admin only


class CredentialPatch(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=80)
    api_key: str | None = Field(None, min_length=8, max_length=400)
    models: dict[str, str] | None = None
    shared_with_users: bool | None = None


def _clean_models(models: dict[str, str]) -> dict[str, str]:
    out = {}
    for k, v in models.items():
        if k not in KINDS:
            raise HTTPException(422, f"Unknown analysis kind {k!r}")
        if v:
            out[k] = v.strip()[:80]
    return out


@router.get("/catalog")
async def model_catalog(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    overrides = await gateway.model_overrides(db)
    return {
        "providers": PROVIDERS,
        "defaults": DEFAULT_MODEL,
        "kinds": KINDS,
        "models": [m.as_dict() for m in catalog(overrides).values()],
    }


@router.get("/credentials")
async def list_credentials(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    own = (await db.scalars(select(ProviderCredential).where(ProviderCredential.user_id == user.id))).all()
    shared_q = select(ProviderCredential).where(ProviderCredential.user_id.is_(None))
    if not user.is_admin:
        shared_q = shared_q.where(ProviderCredential.shared_with_users.is_(True))
    shared = (await db.scalars(shared_q)).all()
    try:
        active = await gateway.resolve_credential(db, user)
        active_info = {
            "scope": active.scope,
            "provider": active.provider,
            "credential_id": str(active.credential_id) if active.credential_id else None,
        }
    except gateway.NoProvider:
        active_info = None
    return {
        "own": [cred_out(c) for c in own],
        "shared": [cred_out(c) | {"key_hint": "…" if not user.is_admin else c.key_hint} for c in shared],
        "active": active_info,
    }


@router.post("/credentials", status_code=201)
async def add_credential(
    body: CredentialIn,
    shared: bool = Query(False),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if shared and not user.is_admin:
        raise HTTPException(403, "Only administrators can add shared keys.")
    if body.provider == "claude_code":
        # Runs on the admin's own Claude plan: Anthropic's terms allow it for the
        # plan owner's own use only, so it can never be shared with other users.
        if not user.is_admin:
            raise HTTPException(403, "Only the administrator can connect Claude Code on the server.")
        if shared:
            raise HTTPException(
                422, "Claude Code uses your own Claude plan and can't be shared with other users."
            )
        if not body.base_url:
            raise HTTPException(422, "Enter the bridge address, e.g. http://192.0.2.10:8789.")
    elif body.base_url and not body.base_url.startswith("https://"):
        raise HTTPException(422, "Provider endpoints must use https://.")
    count = await db.scalar(
        select(func.count())
        .select_from(ProviderCredential)
        .where(ProviderCredential.user_id == (None if shared else user.id))
    )
    if (count or 0) >= 10:
        raise HTTPException(409, "Too many keys.")
    c = ProviderCredential(
        user_id=None if shared else user.id,
        provider=body.provider,
        label=body.label.strip(),
        encrypted_key="pending",
        key_hint=key_hint(body.api_key.strip()),
        base_url=body.base_url,
        models=_clean_models(body.models),
        shared_with_users=shared and body.shared_with_users,
    )
    db.add(c)
    await db.flush()
    c.encrypted_key = secret_box().encrypt(body.api_key.strip(), f"cred:{c.id}")
    await db.commit()
    return cred_out(c)


async def _owned_cred(db: AsyncSession, user: User, cred_id: str) -> ProviderCredential:
    c = await db.get(ProviderCredential, _uuid(cred_id))
    if c is None or (c.user_id != user.id and not (c.user_id is None and user.is_admin)):
        raise HTTPException(404, "Not found")
    return c


@router.patch("/credentials/{cred_id}")
async def update_credential(
    cred_id: str,
    body: CredentialPatch,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    c = await _owned_cred(db, user, cred_id)
    if body.label is not None:
        c.label = body.label.strip()
    if body.api_key is not None:
        c.encrypted_key = secret_box().encrypt(body.api_key.strip(), f"cred:{c.id}")
        c.key_hint = key_hint(body.api_key.strip())
        c.last_test_ok = None
    if body.models is not None:
        c.models = _clean_models(body.models)
    if body.shared_with_users is not None and c.user_id is None:
        c.shared_with_users = body.shared_with_users
    await db.commit()
    return cred_out(c)


@router.delete("/credentials/{cred_id}", status_code=204)
async def delete_credential(
    cred_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    c = await _owned_cred(db, user, cred_id)
    await db.delete(c)
    await db.commit()


@router.post("/credentials/{cred_id}/test")
async def test_credential(
    cred_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    c = await _owned_cred(db, user, cred_id)
    key = secret_box().decrypt(c.encrypted_key, f"cred:{c.id}")
    provider = make_provider(c.provider, key, c.base_url)
    model = (c.models or {}).get("default") or DEFAULT_MODEL[c.provider]
    models: list[str] = []
    try:
        models = await provider.list_models()
        completion = await provider.complete(
            model, Prompt(system="Reply with the single word: ok", user="ping", max_tokens=200)
        )
        me = await db.get(User, user.id)
        assert me
        db.add(
            AIUsage(
                user_id=me.id,
                credential_id=c.id,
                credential_scope="shared" if c.user_id is None else "byok",
                provider=c.provider,
                model=model,
                kind="connection_test",
                input_tokens=completion.usage.input_tokens,
                output_tokens=completion.usage.output_tokens,
            )
        )
        c.last_test_ok, c.last_test_error = True, None
    except ProviderError as e:
        c.last_test_ok, c.last_test_error = False, str(e)[:300]
    c.last_tested_at = utcnow()
    await db.commit()
    return cred_out(c) | {"available_models": models[:200]}


# ------------------------------------------------ Claude Code on this server
@router.get("/claude-code")
async def claude_code_status(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    s = get_settings()
    configured = bool(s.claude_code_bridge_url and s.claude_code_bridge_secret)
    own = (
        await db.scalars(
            select(ProviderCredential).where(
                ProviderCredential.user_id == user.id, ProviderCredential.provider == "claude_code"
            )
        )
    ).first()
    return {
        "available": configured and user.is_admin,
        "configured": configured,
        "connected": cred_out(own) if own else None,
    }


@router.post("/claude-code/connect", status_code=201)
async def claude_code_connect(user: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    """One click: use the server's Claude Code bridge for the admin's own account."""
    s = get_settings()
    if not (s.claude_code_bridge_url and s.claude_code_bridge_secret):
        raise HTTPException(409, "No Claude Code bridge is configured on this server.")
    existing = (
        await db.scalars(
            select(ProviderCredential).where(
                ProviderCredential.user_id == user.id, ProviderCredential.provider == "claude_code"
            )
        )
    ).first()
    c = existing or ProviderCredential(
        user_id=user.id,
        provider="claude_code",
        label="Claude Code on this server",
        encrypted_key="pending",
        key_hint="bridge",
        models={},
    )
    c.base_url = s.claude_code_bridge_url
    if existing is None:
        db.add(c)
        await db.flush()
    c.encrypted_key = secret_box().encrypt(s.claude_code_bridge_secret, f"cred:{c.id}")
    try:
        await make_provider("claude_code", s.claude_code_bridge_secret, c.base_url).list_models()
        c.last_test_ok, c.last_test_error = True, None
    except ProviderError as e:
        c.last_test_ok, c.last_test_error = False, str(e)[:300]
    c.last_tested_at = utcnow()
    me = await db.get(User, user.id)
    assert me
    me.ai_preferred = {**(me.ai_preferred or {}), "credential_id": str(c.id)}  # make it the active provider
    await db.commit()
    return cred_out(c)


class PreferenceIn(BaseModel):
    credential_id: str | None = None
    models: dict[str, str] = Field(default_factory=dict)


@router.put("/preferences")
async def set_preferences(
    body: PreferenceIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    me = await db.get(User, user.id)
    assert me
    if body.credential_id:
        await _owned_cred(db, user, body.credential_id)
    me.ai_preferred = {"credential_id": body.credential_id, "models": _clean_models(body.models)}
    await db.commit()
    return me.ai_preferred


@router.get("/usage")
async def usage(
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    me = await db.get(User, user.id)
    assert me
    since = utcnow() - timedelta(days=days)
    base = select(AIUsage).where(AIUsage.user_id == user.id, AIUsage.created_at >= since)
    rows = (await db.scalars(base)).all()
    status = await gateway.budget_status(db, me)

    def agg(key):
        out: dict = {}
        for r in rows:
            k = key(r)
            b = out.setdefault(
                k,
                {
                    "key": k,
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cost_usd": 0.0,
                    "failed": 0,
                    "price_unknown": 0,
                },
            )
            b["calls"] += 1
            b["input_tokens"] += r.input_tokens
            b["output_tokens"] += r.output_tokens
            b["cache_read_tokens"] += r.cache_read_tokens
            b["cost_usd"] += float(r.cost_usd or 0)
            b["failed"] += 0 if r.success else 1
            b["price_unknown"] += 1 if (r.error or "").startswith("price unknown") else 0
        return sorted(out.values(), key=lambda x: -x["cost_usd"])

    titles = dict(
        (
            await db.execute(
                select(SearchProfile.id, SearchProfile.title).where(SearchProfile.user_id == user.id)
            )
        ).all()
    )
    by_search = agg(lambda r: str(r.search_id) if r.search_id else "none")
    for b in by_search:
        import uuid as _u

        b["title"] = titles.get(_u.UUID(b["key"])) if b["key"] != "none" else "Not tied to a search"
    listing_calls = [
        r for r in rows if r.listing_id and r.kind in ("quick_scan", "deep_analysis", "vision_analysis")
    ]
    listings = {r.listing_id for r in listing_calls}
    deep = [r for r in rows if r.kind == "deep_analysis"]
    return {
        "days": days,
        "budget": status,
        "totals": {
            "calls": len(rows),
            "input_tokens": sum(r.input_tokens for r in rows),
            "output_tokens": sum(r.output_tokens for r in rows),
            "cache_read_tokens": sum(r.cache_read_tokens for r in rows),
            "cost_usd": round(sum(float(r.cost_usd or 0) for r in rows), 6),
            "estimated": True,
            "plan_calls": sum(1 for r in rows if r.provider == "claude_code"),
            "plan_api_equivalent_usd": round(sum(float(r.api_equivalent_usd or 0) for r in rows), 6),
        },
        "avg_cost_per_listing": round(sum(float(r.cost_usd) for r in listing_calls) / len(listings), 6)
        if listings
        else None,
        "avg_cost_per_deep": round(sum(float(r.cost_usd) for r in deep) / len(deep), 6) if deep else None,
        "by_provider": agg(lambda r: r.provider),
        "by_model": agg(lambda r: f"{r.provider}:{r.model}"),
        "by_kind": agg(lambda r: r.kind),
        "by_search": by_search,
        "by_scope": agg(lambda r: r.credential_scope),
        "daily": await gateway.daily_series(db, me, days),
        "recent": [
            {
                "at": r.created_at.isoformat(),
                "kind": r.kind,
                "model": r.model,
                "provider": r.provider,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cost_usd": float(r.cost_usd or 0),
                "success": r.success,
                "error": r.error,
            }
            for r in sorted(rows, key=lambda r: r.created_at, reverse=True)[:50]
        ],
    }


class PricingIn(BaseModel):
    key: str = Field(pattern=r"^(anthropic|openai|gemini):[A-Za-z0-9._\-]{1,80}$")
    label: str | None = Field(None, max_length=80)
    vision: bool | None = None
    structured: bool | None = None
    input_per_m: float | None = Field(None, ge=0, le=1000)
    output_per_m: float | None = Field(None, ge=0, le=1000)
    cache_read_per_m: float | None = Field(None, ge=0, le=1000)


@router.put("/catalog")
async def set_pricing(body: PricingIn, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(AppSetting, "model_catalog")
    if row is None:
        row = AppSetting(key="model_catalog", value={})
        db.add(row)
    provider, model = body.key.split(":", 1)
    entry = dict(
        row.value.get(
            body.key, {"provider": provider, "id": model, "label": model, "vision": False, "structured": True}
        )
    )
    for k, v in body.model_dump(exclude={"key"}, exclude_none=True).items():
        entry[k] = v
    row.value = {**row.value, body.key: entry}
    await db.commit()
    return entry
