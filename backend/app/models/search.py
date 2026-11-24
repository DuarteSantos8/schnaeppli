from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow

SEARCH_STATUSES = ("active", "paused", "archived", "completed")
MATCH_STATUSES = ("new", "seen", "favorite", "interested", "planned", "purchased", "rejected")


class SearchProfile(IdMixin, TimestampMixin, Base):
    """One independent shopping intention."""

    __tablename__ = "search_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    prompt: Mapped[str] = mapped_column(Text, default="")  # original natural-language request
    category: Mapped[str | None] = mapped_column(String(80))
    # Structured interpretation, validated by app.schemas.search.SearchSpec
    spec: Mapped[dict] = mapped_column(default=dict)
    max_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="CHF")
    condition: Mapped[str] = mapped_column(String(10), default="any")  # any | used | new
    prefer_condition: Mapped[str | None] = mapped_column(String(10))  # used | new | None
    # Location override; NULL = use user defaults
    postal_code: Mapped[str | None] = mapped_column(String(10))
    radius_km: Mapped[int | None] = mapped_column(Integer)
    delivery: Mapped[str | None] = mapped_column(String(10))
    # {"ebay": {"enabled": true, "priority": 1}, ...}; empty = all available sources
    sources: Mapped[dict] = mapped_column(default=dict)
    # {"mode": "default"} uses the user's global schedule, or {"mode":"custom","times":["06:30"]}
    # or {"mode":"interval","hours":6}
    schedule: Mapped[dict] = mapped_column(default=lambda: {"mode": "default"})
    notify: Mapped[dict] = mapped_column(default=lambda: {"instant_min_score": 85, "digest": True})
    priority: Mapped[int] = mapped_column(Integer, default=2)  # 1 high, 2 normal, 3 low
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)
    min_score: Mapped[int] = mapped_column(Integer, default=55)

    parent_search_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("search_profiles.id", ondelete="SET NULL")
    )
    last_run_at: Mapped[datetime | None]
    next_run_at: Mapped[datetime | None] = mapped_column(index=True)
    last_error: Mapped[str | None] = mapped_column(String(500))


class SearchRun(IdMixin, Base):
    __tablename__ = "search_runs"

    search_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("search_profiles.id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(12), default="running")  # running|ok|partial|failed
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    new_matches: Mapped[int] = mapped_column(Integer, default=0)
    analyzed: Mapped[int] = mapped_column(Integer, default=0)
    source_report: Mapped[dict] = mapped_column(default=dict)  # per source: count / error
    error: Mapped[str | None] = mapped_column(String(500))


class Listing(IdMixin, Base):
    """A marketplace listing. Public data, shared between users and deduplicated
    by (source, external_id). User-specific state lives in ``SearchMatch``."""

    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_listing_source_ext"),)

    source: Mapped[str] = mapped_column(String(30))
    external_id: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="CHF")
    price_type: Mapped[str] = mapped_column(String(12), default="fixed")  # fixed|auction|negotiable
    shipping_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    shipping_known: Mapped[bool] = mapped_column(Boolean, default=False)
    shipping_possible: Mapped[bool | None]
    pickup_possible: Mapped[bool | None]
    condition: Mapped[str | None] = mapped_column(String(40))  # new|used|refurbished|for_parts|...
    condition_text: Mapped[str | None] = mapped_column(String(200))
    location_text: Mapped[str | None] = mapped_column(String(200))
    postal_code: Mapped[str | None] = mapped_column(String(10))
    country: Mapped[str | None] = mapped_column(String(2))
    lat: Mapped[float | None]
    lon: Mapped[float | None]
    seller: Mapped[dict] = mapped_column(default=dict)  # name, rating, feedback_count
    images: Mapped[list] = mapped_column(default=list)
    ends_at: Mapped[datetime | None]
    is_new_retail: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    state: Mapped[str] = mapped_column(String(10), default="active")  # active|gone
    # Product identification, cached per content hash (not user specific)
    identity: Mapped[dict] = mapped_column(default=dict)


class PricePoint(IdMixin, Base):
    __tablename__ = "price_points"

    listing_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    shipping_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    observed_at: Mapped[datetime] = mapped_column(default=utcnow)


class SearchMatch(IdMixin, Base):
    """A listing in the context of one user's search: score, status, feedback."""

    __tablename__ = "search_matches"
    __table_args__ = (
        UniqueConstraint("search_id", "listing_id", name="uq_match_search_listing"),
        Index("ix_match_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    search_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("search_profiles.id", ondelete="CASCADE"), index=True
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(12), default="new")
    relevance: Mapped[str] = mapped_column(
        String(12), default="pending"
    )  # pending|match|alternative|accessory|bundle|irrelevant
    deal_score: Mapped[int | None] = mapped_column(Integer, index=True)
    deal_label: Mapped[str | None] = mapped_column(String(20))
    effective_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    effective_price_estimated: Mapped[bool] = mapped_column(Boolean, default=True)
    distance_km: Mapped[float | None]
    within_radius: Mapped[bool | None]
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("analyses.id", ondelete="SET NULL")
    )
    analysis_state: Mapped[str] = mapped_column(
        String(12), default="queued"
    )  # queued|done|skipped|limited|failed
    skip_reason: Mapped[str | None] = mapped_column(String(200))
    price_at_analysis: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    previous_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    price_dropped_at: Mapped[datetime | None]
    first_seen_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    notified_at: Mapped[datetime | None]
    digested_at: Mapped[datetime | None]
    feedback_at: Mapped[datetime | None]
    note: Mapped[str | None] = mapped_column(String(500))


class Analysis(IdMixin, Base):
    """Result of an AI evaluation. Separates observed facts from AI assumptions."""

    __tablename__ = "analyses"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    search_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("search_profiles.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(20))  # quick_scan | deep_analysis | vision_analysis
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(80))
    result: Mapped[dict] = mapped_column(default=dict)
    score: Mapped[int | None] = mapped_column(Integer)
    score_breakdown: Mapped[dict] = mapped_column(default=dict)
    label: Mapped[str | None] = mapped_column(String(20))
    market_value: Mapped[dict] = mapped_column(default=dict)  # low/high/basis/confidence/source
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class WishlistItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "wishlist_items"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("wishlist_items.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(12), default="main")  # main | accessory
    category: Mapped[str | None] = mapped_column(String(80))
    essential: Mapped[bool] = mapped_column(Boolean, default=False)
    budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    compatibility: Mapped[dict] = mapped_column(default=dict)  # e.g. {"mount":"Sony E", "battery":"NP-FW50"}
    status: Mapped[str] = mapped_column(
        String(12), default="planned"
    )  # planned|interested|purchased|rejected
    search_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("search_profiles.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Purchase(IdMixin, TimestampMixin, Base):
    """Budget ledger entry. A found listing is never counted as spent automatically."""

    __tablename__ = "purchases"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="CHF")
    category: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(
        String(12), default="planned"
    )  # planned|interested|purchased|rejected
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    match_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("search_matches.id", ondelete="SET NULL")
    )
    wishlist_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("wishlist_items.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(String(500))


class CustomShop(IdMixin, TimestampMixin, Base):
    """A shop the user added; searched with every one of their searches
    (see app/sources/shops.py)."""

    __tablename__ = "custom_shops"
    __table_args__ = (UniqueConstraint("user_id", "host", name="uq_custom_shop_user_host"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    host: Mapped[str] = mapped_column(String(120))
    mode: Mapped[str] = mapped_column(String(8))  # woo | page
    search_url: Mapped[str] = mapped_column(String(1000))  # contains {query}
    kind: Mapped[str] = mapped_column(String(12), default="retail")  # retail | secondhand
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(String(12), default="untested")
    state_detail: Mapped[str | None] = mapped_column(String(300))
    checked_at: Mapped[datetime | None]
    paused_until: Mapped[datetime | None]
    found_total: Mapped[int] = mapped_column(Integer, default=0)
