from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


def default_notification_prefs() -> dict:
    return {
        "instant_exceptional": True,
        "instant_good": False,
        "price_drops": True,
        "search_failures": True,
        "usage_warnings": True,
        "digest_enabled": True,
        "digest_times": ["07:00", "18:00"],
        "digest_days": [0, 1, 2, 3, 4, 5, 6],  # Monday = 0
        "digest_min_score": 60,
        "digest_max_results": 8,
        "digest_include_price_drops": True,
        "digest_include_alternatives": True,
        "digest_include_accessories": True,
        "quiet_hours": None,
    }


def default_search_schedule() -> dict:
    # Default global search runs, before each digest.
    return {"times": ["06:30", "17:30"]}


def default_ai_limits() -> dict:
    return {
        "monthly_limit_usd": 10.0,
        "daily_limit_usd": 1.0,
        "warn_pct": 75,
        "pause_pct": 100,
        "max_deep_per_day": 20,
        "max_vision_per_day": 20,
        "max_analyses_per_run": 15,
        "auto_pause": True,
    }


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Zurich")
    currency: Mapped[str] = mapped_column(String(3), default="CHF")
    locale: Mapped[str] = mapped_column(String(10), default="en")

    # Location: postal code / city are enough; street is never stored.
    country: Mapped[str] = mapped_column(String(2), default="CH")
    postal_code: Mapped[str | None] = mapped_column(String(10))
    city: Mapped[str | None] = mapped_column(String(80))
    lat: Mapped[float | None]
    lon: Mapped[float | None]
    radius_km: Mapped[int] = mapped_column(Integer, default=50)
    delivery: Mapped[str] = mapped_column(String(10), default="both")  # ship | pickup | both

    monthly_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    notification_prefs: Mapped[dict] = mapped_column(default=default_notification_prefs)
    search_schedule: Mapped[dict] = mapped_column(default=default_search_schedule)
    ai_limits: Mapped[dict] = mapped_column(default=default_ai_limits)
    ai_paused_reason: Mapped[str | None] = mapped_column(String(200))
    ai_preferred: Mapped[dict] = mapped_column(
        default=dict
    )  # {"provider":..,"credential_id":..,"models":{kind:model}}
    share_location_with_ai: Mapped[bool] = mapped_column(Boolean, default=False)

    # Transparent, resettable learned preferences (see services/learning.py).
    learned_prefs: Mapped[dict] = mapped_column(default=dict)
    # Appearance and layout choices (theme, accent, density, start page, phone tabs).
    ui_prefs: Mapped[dict] = mapped_column(default=dict)

    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    last_digest_at: Mapped[datetime | None]


class Session(IdMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))


class Invite(IdMixin, Base):
    __tablename__ = "invites"

    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    used_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    used_at: Mapped[datetime | None]
    note: Mapped[str | None] = mapped_column(String(120))


class AuditLog(IdMixin, Base):
    """Security relevant events. Never stores secrets or passwords."""

    __tablename__ = "audit_log"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    event: Mapped[str] = mapped_column(String(60), index=True)
    ip: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
