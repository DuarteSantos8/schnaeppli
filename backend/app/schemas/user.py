from __future__ import annotations

from typing import Literal
from zoneinfo import available_timezones

from pydantic import BaseModel, Field, field_validator

from app.models import User

Delivery = Literal["ship", "pickup", "both"]


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    is_admin: bool
    timezone: str
    currency: str
    locale: str
    country: str
    postal_code: str | None
    city: str | None
    has_coordinates: bool
    radius_km: int
    delivery: str
    monthly_budget: float | None
    notification_prefs: dict
    search_schedule: dict
    ai_limits: dict
    ai_paused_reason: str | None
    ai_preferred: dict
    share_location_with_ai: bool
    learned_prefs: dict
    ui_prefs: dict


def user_out(u: User) -> UserOut:
    return UserOut(
        id=str(u.id),
        email=u.email,
        display_name=u.display_name,
        is_admin=u.is_admin,
        timezone=u.timezone,
        currency=u.currency,
        locale=u.locale,
        country=u.country,
        postal_code=u.postal_code,
        city=u.city,
        has_coordinates=u.lat is not None,
        radius_km=u.radius_km,
        delivery=u.delivery,
        monthly_budget=float(u.monthly_budget) if u.monthly_budget is not None else None,
        notification_prefs=u.notification_prefs or {},
        search_schedule=u.search_schedule or {},
        ai_limits=u.ai_limits or {},
        ai_paused_reason=u.ai_paused_reason,
        ai_preferred=u.ai_preferred or {},
        share_location_with_ai=u.share_location_with_ai,
        learned_prefs=u.learned_prefs or {},
        ui_prefs=UIPrefs(**(u.ui_prefs or {})).model_dump(),
    )


_TIME = r"^([01]\d|2[0-3]):[0-5]\d$"


class NotificationPrefs(BaseModel):
    instant_exceptional: bool = True
    instant_good: bool = False
    price_drops: bool = True
    search_failures: bool = True
    usage_warnings: bool = True
    digest_enabled: bool = True
    digest_times: list[str] = Field(default_factory=lambda: ["07:00", "18:00"], max_length=6)
    digest_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    digest_min_score: int = Field(60, ge=0, le=100)
    digest_max_results: int = Field(8, ge=1, le=30)
    digest_include_price_drops: bool = True
    digest_include_alternatives: bool = True
    digest_include_accessories: bool = True
    quiet_hours: list[str] | None = None

    @field_validator("digest_times")
    @classmethod
    def _times(cls, v: list[str]) -> list[str]:
        import re

        for t in v:
            if not re.match(_TIME, t):
                raise ValueError(f"invalid time {t!r}, use HH:MM")
        return sorted(set(v))

    @field_validator("digest_days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("days are 0 (Monday) … 6 (Sunday)")
        return sorted(set(v))


class SearchSchedule(BaseModel):
    times: list[str] = Field(default_factory=lambda: ["06:30", "17:30"], min_length=1, max_length=12)

    @field_validator("times")
    @classmethod
    def _times(cls, v: list[str]) -> list[str]:
        import re

        for t in v:
            if not re.match(_TIME, t):
                raise ValueError(f"invalid time {t!r}, use HH:MM")
        return sorted(set(v))


class AILimits(BaseModel):
    monthly_limit_usd: float = Field(10.0, ge=0, le=10_000)
    daily_limit_usd: float = Field(1.0, ge=0, le=1_000)
    warn_pct: int = Field(75, ge=1, le=100)
    pause_pct: int = Field(100, ge=1, le=200)
    max_deep_per_day: int = Field(20, ge=0, le=1000)
    max_vision_per_day: int = Field(20, ge=0, le=1000)
    max_analyses_per_run: int = Field(15, ge=0, le=500)
    auto_pause: bool = True


NavTab = Literal["home", "deals", "searches", "wishlist", "assistant", "budget", "usage"]


class UIPrefs(BaseModel):
    """Appearance and layout. Unknown or stale keys are dropped on read."""

    model_config = {"extra": "ignore"}

    theme: Literal["system", "light", "dark"] = "system"
    accent: Literal["cobalt", "forest", "plum", "ember", "graphite"] = "cobalt"
    density: Literal["comfortable", "compact"] = "comfortable"
    text_size: Literal["default", "large"] = "default"
    start_page: NavTab = "home"
    deal_layout: Literal["cards", "rows"] = "cards"
    phone_tabs: list[NavTab] = Field(default_factory=lambda: ["home", "deals", "searches", "assistant"])
    show_photos: bool = True
    reduce_motion: bool = False
    home_sections: list[Literal["stats", "best", "drops", "activity"]] = Field(
        default_factory=lambda: ["stats", "best", "drops", "activity"]
    )

    @field_validator("phone_tabs")
    @classmethod
    def _tabs(cls, v: list[str]) -> list[str]:
        out = list(dict.fromkeys(v))
        if len(out) != 4:
            raise ValueError("choose exactly four tabs")
        return out

    @field_validator("home_sections")
    @classmethod
    def _sections(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=80)
    timezone: str | None = None
    currency: Literal["CHF", "EUR", "USD", "GBP"] | None = None
    locale: Literal["en", "de", "fr", "it"] | None = None
    country: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    postal_code: str | None = Field(None, max_length=10, pattern=r"^[A-Za-z0-9 -]{0,10}$")
    city: str | None = Field(None, max_length=80)
    radius_km: int | None = Field(None, ge=1, le=1000)
    delivery: Delivery | None = None
    monthly_budget: float | None = Field(None, ge=0, le=1_000_000)
    notification_prefs: NotificationPrefs | None = None
    search_schedule: SearchSchedule | None = None
    ai_limits: AILimits | None = None
    share_location_with_ai: bool | None = None
    ui_prefs: UIPrefs | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is not None and v not in available_timezones():
            raise ValueError("unknown timezone")
        return v
