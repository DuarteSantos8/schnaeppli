"""The structured search profile. The AI produces a ``SearchDraft``; the user
reviews and edits it before it becomes a ``SearchProfile``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProductTarget(BaseModel):
    name: str = Field(max_length=120, description="Product or model name, e.g. 'Sony Alpha 6400'")
    reason: str | None = Field(
        default=None, max_length=300, description="Why this is relevant (required for alternatives)"
    )


class AccessoryTarget(BaseModel):
    name: str = Field(max_length=120)
    essential: bool = False
    max_budget: float | None = None
    compatibility: str | None = Field(default=None, max_length=200, description="e.g. 'Sony E-mount'")


class SearchSpec(BaseModel):
    desired_products: list[ProductTarget] = Field(default_factory=list, max_length=20)
    alternatives: list[ProductTarget] = Field(default_factory=list, max_length=20)
    allow_alternatives: bool = True
    excluded: list[str] = Field(
        default_factory=list, max_length=30, description="Products/keywords to exclude"
    )
    preferred_brands: list[str] = Field(default_factory=list, max_length=15)
    accessories: list[AccessoryTarget] = Field(default_factory=list, max_length=20)
    must_have: list[str] = Field(default_factory=list, max_length=15, description="Hard requirements")
    nice_to_have: list[str] = Field(default_factory=list, max_length=15)
    queries: list[str] = Field(
        default_factory=list, max_length=12, description="Concrete marketplace search queries to run"
    )
    notes: str | None = Field(default=None, max_length=1000)


class SearchDraft(BaseModel):
    """What the AI understood. Every field is editable by the user."""

    title: str = Field(max_length=120)
    category: str | None = Field(default=None, max_length=80)
    spec: SearchSpec
    max_budget: float | None = None
    currency: str = "CHF"
    condition: Literal["any", "used", "new"] = "any"
    prefer_condition: Literal["used", "new"] | None = None
    delivery: Literal["ship", "pickup", "both"] | None = None
    radius_km: int | None = None
    priority: int = Field(default=2, ge=1, le=3)
    summary: str = Field(default="", max_length=800, description="One-paragraph plain-language summary")


class InterpretationResult(BaseModel):
    """Structured output of the prompt-interpretation call."""

    needs_clarification: bool
    questions: list[str] = Field(default_factory=list, max_length=4)
    draft: SearchDraft
    assumptions: list[str] = Field(
        default_factory=list, max_length=8, description="Things the AI assumed that the user should check"
    )


Status = Literal["active", "paused", "archived", "completed"]


class SearchIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    prompt: str = Field(default="", max_length=4000)
    category: str | None = Field(default=None, max_length=80)
    spec: SearchSpec = Field(default_factory=SearchSpec)
    max_budget: float | None = Field(default=None, ge=0, le=10_000_000)
    currency: str = Field(default="CHF", pattern=r"^[A-Z]{3}$")
    condition: Literal["any", "used", "new"] = "any"
    prefer_condition: Literal["used", "new"] | None = None
    postal_code: str | None = Field(default=None, max_length=10, pattern=r"^[A-Za-z0-9 -]{0,10}$")
    radius_km: int | None = Field(default=None, ge=1, le=1000)
    delivery: Literal["ship", "pickup", "both"] | None = None
    sources: dict[str, dict] = Field(default_factory=dict)
    schedule: dict = Field(default_factory=lambda: {"mode": "default"})
    notify: dict = Field(default_factory=lambda: {"instant_min_score": 85, "digest": True})
    priority: int = Field(default=2, ge=1, le=3)
    status: Status = "active"
    min_score: int = Field(default=55, ge=0, le=100)
    parent_search_id: str | None = None


class SearchPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=80)
    spec: SearchSpec | None = None
    max_budget: float | None = Field(default=None, ge=0, le=10_000_000)
    condition: Literal["any", "used", "new"] | None = None
    prefer_condition: Literal["used", "new"] | None = None
    postal_code: str | None = Field(default=None, max_length=10, pattern=r"^[A-Za-z0-9 -]{0,10}$")
    radius_km: int | None = Field(default=None, ge=1, le=1000)
    delivery: Literal["ship", "pickup", "both"] | None = None
    sources: dict[str, dict] | None = None
    schedule: dict | None = None
    notify: dict | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    status: Status | None = None
    min_score: int | None = Field(default=None, ge=0, le=100)
