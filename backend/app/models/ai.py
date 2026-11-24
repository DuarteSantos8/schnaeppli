from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow

ANALYSIS_KINDS = (
    "prompt_interpretation",
    "quick_scan",
    "deep_analysis",
    "vision_analysis",
    "market_comparison",
    "digest_generation",
    "chat",
    "connection_test",
)


class ProviderCredential(IdMixin, TimestampMixin, Base):
    """An AI provider API key, AES-GCM encrypted at rest. ``user_id`` NULL = shared
    credential configured by an administrator."""

    __tablename__ = "provider_credentials"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(80))
    encrypted_key: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(12))  # last 4 chars, for display only
    base_url: Mapped[str | None] = mapped_column(String(300))  # OpenAI-compatible endpoints
    models: Mapped[dict] = mapped_column(default=dict)  # analysis kind -> model id
    shared_with_users: Mapped[bool] = mapped_column(Boolean, default=False)
    last_tested_at: Mapped[datetime | None]
    last_test_ok: Mapped[bool | None]
    last_test_error: Mapped[str | None] = mapped_column(String(300))


class AIUsage(IdMixin, Base):
    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_usage_user_time", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("provider_credentials.id", ondelete="SET NULL")
    )
    credential_scope: Mapped[str] = mapped_column(String(8))  # byok | shared
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(30), index=True)
    search_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("search_profiles.id", ondelete="SET NULL")
    )
    listing_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("listings.id", ondelete="SET NULL"))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)
    cost_estimated: Mapped[bool] = mapped_column(Boolean, default=True)
    # Subscription providers: what the tokens would have cost on the API (not billed).
    api_equivalent_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ChatThread(IdMixin, TimestampMixin, Base):
    __tablename__ = "chat_threads"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="New conversation")
    search_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("search_profiles.id", ondelete="SET NULL")
    )


class ChatMessage(IdMixin, Base):
    __tablename__ = "chat_messages"

    thread_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_threads.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    refs: Mapped[dict] = mapped_column(default=dict)  # match ids referenced
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TelegramLink(IdMixin, Base):
    __tablename__ = "telegram_links"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    chat_id: Mapped[str | None] = mapped_column(String(40))
    username: Mapped[str | None] = mapped_column(String(64))
    code_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    code_expires_at: Mapped[datetime | None]
    linked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Notification(IdMixin, Base):
    """Outbox / history of every notification sent (or skipped)."""

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(
        String(30)
    )  # deal_alert|digest|price_drop|search_status|usage_warning|search_failure
    channel: Mapped[str] = mapped_column(String(12), default="telegram")
    match_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("search_matches.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="sent")  # sent|failed|skipped
    error: Mapped[str | None] = mapped_column(String(300))
    dedupe_key: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class AppSetting(Base):
    """Admin key/value settings (e.g. which sources are enabled instance-wide)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


__all__ = [
    "AIUsage",
    "AppSetting",
    "ChatMessage",
    "ChatThread",
    "Notification",
    "ProviderCredential",
    "TelegramLink",
]
