"""Single entry point for every AI call: picks the credential and model, enforces
spending limits *before* the call, records the provider-reported usage after it.

Nothing bypasses this module, so limits can't be silently exceeded.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TypeVar
from zoneinfo import ZoneInfo

import structlog
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.catalog import DEFAULT_MODEL, PLAN_PROVIDERS, ModelInfo, estimate_cost, lookup
from app.ai.providers import Completion, Prompt, ProviderError, make_provider
from app.core.config import get_settings
from app.core.db import utcnow
from app.core.security import secret_box
from app.models import AIUsage, AppSetting, ProviderCredential, User

log = structlog.get_logger()
T = TypeVar("T", bound=BaseModel)

EFFORT = {
    "prompt_interpretation": "medium",
    "quick_scan": "low",
    "deep_analysis": "medium",
    "vision_analysis": "low",
    "market_comparison": "low",
    "digest_generation": "low",
    "chat": "medium",
    "connection_test": "low",
}
# Rough upper bounds used to reserve budget before a call.
RESERVE_TOKENS = {
    "prompt_interpretation": (3000, 2500),
    "quick_scan": (2500, 1200),
    "deep_analysis": (5000, 3000),
    "vision_analysis": (6000, 1500),
    "market_comparison": (4000, 1500),
    "digest_generation": (4000, 1500),
    "chat": (8000, 2500),
    "connection_test": (50, 20),
}


class BudgetExceeded(Exception):
    def __init__(self, message: str, *, paused: bool = False):
        super().__init__(message)
        self.paused = paused


class NoProvider(Exception):
    pass


@dataclass
class ResolvedCredential:
    credential_id: uuid.UUID | None
    scope: str  # byok | shared
    provider: str
    api_key: str
    base_url: str | None
    models: dict


async def model_overrides(db: AsyncSession) -> dict:
    row = await db.get(AppSetting, "model_catalog")
    return row.value if row else {}


async def resolve_credential(db: AsyncSession, user: User) -> ResolvedCredential:
    pref = user.ai_preferred or {}
    q = select(ProviderCredential).where(ProviderCredential.user_id == user.id)
    if pref.get("credential_id"):
        try:
            q = q.where(ProviderCredential.id == uuid.UUID(pref["credential_id"]))
        except ValueError:
            pass
    own = (await db.scalars(q.order_by(ProviderCredential.created_at))).first()
    if own is not None:
        return ResolvedCredential(
            own.id,
            "byok",
            own.provider,
            secret_box().decrypt(own.encrypted_key, f"cred:{own.id}"),
            own.base_url,
            own.models or {},
        )
    shared = (
        await db.scalars(
            select(ProviderCredential)
            .where(ProviderCredential.user_id.is_(None), ProviderCredential.shared_with_users.is_(True))
            .order_by(ProviderCredential.created_at)
        )
    ).first()
    if shared is not None:
        return ResolvedCredential(
            shared.id,
            "shared",
            shared.provider,
            secret_box().decrypt(shared.encrypted_key, f"cred:{shared.id}"),
            shared.base_url,
            shared.models or {},
        )
    s = get_settings()
    if s.shared_ai_provider and s.shared_ai_api_key:
        models = {"default": s.shared_ai_model} if s.shared_ai_model else {}
        return ResolvedCredential(None, "shared", s.shared_ai_provider, s.shared_ai_api_key, None, models)
    raise NoProvider("No AI provider is configured. Add an API key in Settings → AI.")


def pick_model(cred: ResolvedCredential, user: User, kind: str) -> str:
    pref_models = (user.ai_preferred or {}).get("models", {})
    return (
        pref_models.get(kind)
        or cred.models.get(kind)
        or pref_models.get("default")
        or cred.models.get("default")
        or DEFAULT_MODEL[cred.provider]
    )


def _local_day_start(user: User, now: datetime) -> datetime:
    tz = ZoneInfo(user.timezone or "Europe/Zurich")
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(ZoneInfo("UTC"))


def _local_month_start(user: User, now: datetime) -> datetime:
    tz = ZoneInfo(user.timezone or "Europe/Zurich")
    local = now.astimezone(tz)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(ZoneInfo("UTC"))


async def spend_since(db: AsyncSession, user_id: uuid.UUID, since: datetime) -> float:
    total = await db.scalar(
        select(func.coalesce(func.sum(AIUsage.cost_usd), 0)).where(
            AIUsage.user_id == user_id, AIUsage.created_at >= since
        )
    )
    return float(total or 0)


async def count_since(db: AsyncSession, user_id: uuid.UUID, kind: str, since: datetime) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(AIUsage)
            .where(
                AIUsage.user_id == user_id,
                AIUsage.kind == kind,
                AIUsage.created_at >= since,
                AIUsage.success.is_(True),
            )
        )
        or 0
    )


async def budget_status(db: AsyncSession, user: User) -> dict:
    now = utcnow()
    limits = user.ai_limits or {}
    day = await spend_since(db, user.id, _local_day_start(user, now))
    month = await spend_since(db, user.id, _local_month_start(user, now))
    return {
        "day_usd": round(day, 6),
        "month_usd": round(month, 6),
        "daily_limit_usd": limits.get("daily_limit_usd"),
        "monthly_limit_usd": limits.get("monthly_limit_usd"),
        "warn_pct": limits.get("warn_pct", 75),
        "pause_pct": limits.get("pause_pct", 100),
        "paused_reason": user.ai_paused_reason,
    }


async def check_budget(db: AsyncSession, user: User, kind: str, info: ModelInfo) -> None:
    """Raises BudgetExceeded if this call could push the user past a limit."""
    if kind == "connection_test":
        return
    if user.ai_paused_reason and kind not in ("chat", "prompt_interpretation"):
        raise BudgetExceeded(f"AI analysis is paused: {user.ai_paused_reason}", paused=True)
    limits = user.ai_limits or {}
    now = utcnow()
    if info.provider in PLAN_PROVIDERS:
        await _check_counts(db, user, kind, limits, now)
        return
    in_t, out_t = RESERVE_TOKENS.get(kind, (4000, 2000))
    reserve, _ = estimate_cost(info, in_t, out_t)
    pause_pct = limits.get("pause_pct", 100) / 100
    for label, limit, since in (
        ("daily", limits.get("daily_limit_usd"), _local_day_start(user, now)),
        ("monthly", limits.get("monthly_limit_usd"), _local_month_start(user, now)),
    ):
        if limit is None:
            continue
        spent = await spend_since(db, user.id, since)
        if spent + reserve > float(limit) * pause_pct:
            if limits.get("auto_pause", True) and label == "monthly":
                user.ai_paused_reason = "monthly AI budget reached"
                await db.commit()
            raise BudgetExceeded(
                f"The {label} AI budget (${float(limit):.2f}) would be exceeded "
                f"(${spent:.2f} used). Raise the limit in Settings → AI to continue.",
                paused=label == "monthly",
            )
    await _check_counts(db, user, kind, limits, now)


async def _check_counts(db: AsyncSession, user: User, kind: str, limits: dict, now: datetime) -> None:
    day_start = _local_day_start(user, now)
    if kind == "deep_analysis" and await count_since(db, user.id, kind, day_start) >= limits.get(
        "max_deep_per_day", 20
    ):
        raise BudgetExceeded("Daily limit for deep analyses reached.")
    if kind == "vision_analysis" and await count_since(db, user.id, kind, day_start) >= limits.get(
        "max_vision_per_day", 20
    ):
        raise BudgetExceeded("Daily limit for image analyses reached.")


async def call(
    db: AsyncSession,
    user: User,
    kind: str,
    prompt: Prompt,
    schema: type[T] | None = None,
    *,
    search_id: uuid.UUID | None = None,
    listing_id: uuid.UUID | None = None,
    require_vision: bool = False,
) -> tuple[Completion, AIUsage]:
    cred = await resolve_credential(db, user)
    model = pick_model(cred, user, kind)
    info = lookup(cred.provider, model, await model_overrides(db))
    if require_vision and not info.vision:
        raise ProviderError(
            f"{info.label} does not support image input; choose a vision model for image analysis."
        )
    if prompt.images and not info.vision:
        prompt.images = []
    await check_budget(db, user, kind, info)
    prompt.effort = EFFORT.get(kind, "low")

    provider = make_provider(cred.provider, cred.api_key, cred.base_url)
    usage_row = AIUsage(
        user_id=user.id,
        credential_id=cred.credential_id,
        credential_scope=cred.scope,
        provider=cred.provider,
        model=model,
        kind=kind,
        search_id=search_id,
        listing_id=listing_id,
    )
    try:
        completion = await provider.complete(model, prompt, schema)
    except ProviderError as e:
        usage_row.success = False
        usage_row.error = str(e)[:300]
        usage_row.cost_usd = Decimal(0)
        db.add(usage_row)
        await db.commit()
        log.warning("ai_call_failed", kind=kind, provider=cred.provider, model=model, error=str(e))
        raise

    u = completion.usage
    cost, known = estimate_cost(
        info, u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens
    )
    usage_row.input_tokens = u.input_tokens
    usage_row.output_tokens = u.output_tokens
    usage_row.cache_read_tokens = u.cache_read_tokens
    usage_row.cache_write_tokens = u.cache_write_tokens
    usage_row.cost_usd = Decimal(str(round(cost, 6)))
    # No provider reports a monetary cost, so every figure is an estimate; a
    # missing price uses the conservative fallback rate and is flagged too.
    usage_row.cost_estimated = True
    usage_row.error = None if known else "price unknown: conservative fallback rate used"
    if cred.provider in PLAN_PROVIDERS:
        usage_row.cost_usd = Decimal(0)
        usage_row.cost_estimated = False
        usage_row.error = None
        if completion.api_equivalent_usd is not None:
            usage_row.api_equivalent_usd = Decimal(str(round(float(completion.api_equivalent_usd), 6)))
    db.add(usage_row)
    await db.commit()
    await _maybe_warn(db, user)
    log.info(
        "ai_call",
        kind=kind,
        provider=cred.provider,
        model=model,
        in_tokens=u.input_tokens,
        out_tokens=u.output_tokens,
        cost_usd=round(cost, 6),
    )
    return completion, usage_row


async def _maybe_warn(db: AsyncSession, user: User) -> None:
    """Queue a one-per-period usage warning when crossing the warn threshold."""
    from app.services.notify import queue_usage_warning

    status = await budget_status(db, user)
    warn = status["warn_pct"] / 100
    for period, spent, limit in (
        ("day", status["day_usd"], status["daily_limit_usd"]),
        ("month", status["month_usd"], status["monthly_limit_usd"]),
    ):
        if limit and spent >= float(limit) * warn:
            await queue_usage_warning(db, user, period, spent, float(limit))


async def daily_series(db: AsyncSession, user: User, days: int = 30) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    rows = (
        await db.execute(
            select(AIUsage.created_at, AIUsage.cost_usd, AIUsage.input_tokens, AIUsage.output_tokens).where(
                AIUsage.user_id == user.id, AIUsage.created_at >= since
            )
        )
    ).all()
    tz = ZoneInfo(user.timezone or "Europe/Zurich")
    buckets: dict[str, dict] = {}
    for created, cost, i, o in rows:
        d = created.astimezone(tz).date().isoformat()
        b = buckets.setdefault(d, {"date": d, "cost_usd": 0.0, "tokens": 0, "calls": 0})
        b["cost_usd"] += float(cost or 0)
        b["tokens"] += (i or 0) + (o or 0)
        b["calls"] += 1
    return [buckets[k] for k in sorted(buckets)]
