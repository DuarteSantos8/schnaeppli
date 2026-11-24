"""Marketplace adapter interface.

Every source is an independent adapter. An adapter must only use permitted access
methods (official APIs, user-forwarded data, or single user-initiated page fetches
that robots.txt allows). Sources without such a method are registered as
``unsupported`` with an explanation, so the UI never pretends they work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

SourceState = Literal["ready", "needs_credentials", "unsupported", "planned", "manual"]


@dataclass
class SourceStatus:
    state: SourceState
    reason: str
    docs: str | None = None
    alternatives: str | None = None

    @property
    def available(self) -> bool:
        return self.state == "ready"


@dataclass
class SearchQuery:
    text: str
    max_price: float | None = None
    currency: str = "CHF"
    condition: str = "any"  # any | used | new
    country: str = "CH"
    limit: int = 50


@dataclass
class RawListing:
    source: str
    external_id: str
    url: str
    title: str
    description: str | None = None
    price: Decimal | None = None
    currency: str = "CHF"
    price_type: str = "fixed"
    shipping_cost: Decimal | None = None
    shipping_known: bool = False
    shipping_possible: bool | None = None
    pickup_possible: bool | None = None
    condition: str | None = None
    condition_text: str | None = None
    location_text: str | None = None
    postal_code: str | None = None
    country: str | None = None
    seller: dict = field(default_factory=dict)
    images: list[str] = field(default_factory=list)
    ends_at: datetime | None = None
    is_new_retail: bool = False


class SourceError(Exception):
    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class SourceAdapter:
    id: str
    name: str
    kind: Literal["secondhand", "retail", "mixed"]
    region: str = "CH"
    homepage: str = ""

    def status(self) -> SourceStatus:
        raise NotImplementedError

    async def search(self, query: SearchQuery) -> list[RawListing]:
        raise SourceError(f"{self.name} does not support automated search.", retryable=False)


class UnsupportedSource(SourceAdapter):
    """A marketplace without a permitted automated interface."""

    def __init__(
        self,
        id: str,
        name: str,
        kind,
        homepage: str,
        reason: str,
        alternatives: str | None = None,
        state: SourceState = "unsupported",
    ):
        self.id, self.name, self.kind, self.homepage = id, name, kind, homepage
        self._status = SourceStatus(state, reason, alternatives=alternatives)

    def status(self) -> SourceStatus:
        return self._status
