"""eBay Browse API (official). Needs an eBay developer application (free):
https://developer.ebay.com → Application keys → Production keyset.

Uses the client-credentials grant with the public ``api_scope``; no user eBay
login is involved. Returns *asking* prices (Browse API has no sold prices).
"""

from __future__ import annotations

import base64
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation

import httpx

from app.core.config import get_settings
from app.sources.base import RawListing, SearchQuery, SourceAdapter, SourceError, SourceStatus

SCOPE = "https://api.ebay.com/oauth/api_scope"
HOSTS = {"production": "https://api.ebay.com", "sandbox": "https://api.sandbox.ebay.com"}

# eBay condition IDs: https://developer.ebay.com/api-docs/sell/static/metadata/condition-id-values.html
USED_IDS = "2010|2020|2030|2500|2750|3000|4000|5000|6000"
NEW_IDS = "1000|1500"


def _dec(v) -> Decimal | None:
    try:
        return Decimal(str(v)) if v is not None else None
    except InvalidOperation:
        return None


def _condition(cond_id: str | None, text: str | None) -> str | None:
    if not cond_id:
        return None
    i = int(cond_id) if cond_id.isdigit() else 0
    if i in (1000, 1500):
        return "new"
    if i in (2000, 2010, 2020, 2030, 2500):
        return "refurbished"
    if i == 7000:
        return "for_parts"
    if i:
        return "used"
    return (text or "").lower() or None


class EbayAdapter(SourceAdapter):
    id = "ebay"
    name = "eBay"
    kind = "mixed"
    homepage = "https://www.ebay.ch"

    _token: str | None = None
    _token_exp: float = 0

    def __init__(self) -> None:
        s = get_settings()
        self.marketplace = s.ebay_marketplace
        self.base = HOSTS.get(s.ebay_environment, HOSTS["production"])

    def status(self) -> SourceStatus:
        s = get_settings()
        if not (s.ebay_client_id and s.ebay_client_secret):
            return SourceStatus(
                "needs_credentials",
                "Official eBay Browse API. The administrator needs to add an eBay developer "
                "application key (free) to the server configuration.",
                docs="docs/marketplaces.md#ebay",
            )
        return SourceStatus(
            "ready", f"Official eBay Browse API ({self.marketplace}). Asking prices, not sold prices."
        )

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        if EbayAdapter._token and time.time() < EbayAdapter._token_exp - 120:
            return EbayAdapter._token
        s = get_settings()
        basic = base64.b64encode(f"{s.ebay_client_id}:{s.ebay_client_secret}".encode()).decode()
        resp = await client.post(
            f"{self.base}/identity/v1/oauth2/token",
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials", "scope": SCOPE},
        )
        if resp.status_code in (400, 401):
            raise SourceError("eBay rejected the application credentials.", retryable=False)
        resp.raise_for_status()
        data = resp.json()
        EbayAdapter._token = data["access_token"]
        EbayAdapter._token_exp = time.time() + int(data.get("expires_in", 7200))
        return EbayAdapter._token

    def _filters(self, q: SearchQuery) -> str:
        parts = []
        if q.max_price:
            parts += [f"price:[..{q.max_price:.0f}]", f"priceCurrency:{q.currency}"]
        if q.condition == "used":
            parts.append(f"conditionIds:{{{USED_IDS}}}")
        elif q.condition == "new":
            parts.append(f"conditionIds:{{{NEW_IDS}}}")
        if q.country:
            parts.append(f"deliveryCountry:{q.country}")
        return ",".join(parts)

    async def search(self, query: SearchQuery) -> list[RawListing]:
        if not self.status().available:
            raise SourceError("eBay is not configured.", retryable=False)
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                token = await self._get_token(client)
                params = {"q": query.text[:100], "limit": str(min(query.limit, 100))}
                f = self._filters(query)
                if f:
                    params["filter"] = f
                resp = await client.get(
                    f"{self.base}/buy/browse/v1/item_summary/search",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
                        # Country only: the user's postal code is not shared with eBay.
                        "X-EBAY-C-ENDUSERCTX": f"contextualLocation=country={query.country}",
                        "Accept-Language": "de-CH",
                    },
                )
            except httpx.HTTPError as e:
                raise SourceError(f"eBay request failed: {type(e).__name__}") from e
        if resp.status_code == 429:
            raise SourceError("eBay rate limit reached.")
        if resp.status_code >= 400:
            msg = ""
            try:
                msg = resp.json().get("errors", [{}])[0].get("message", "")
            except ValueError:
                pass
            raise SourceError(
                f"eBay error {resp.status_code}: {msg[:150]}", retryable=resp.status_code >= 500
            )
        return [self._parse(i) for i in resp.json().get("itemSummaries", []) or []]

    def _parse(self, item: dict) -> RawListing:
        price = item.get("price") or item.get("currentBidPrice") or {}
        ship_cost, ship_known = None, False
        for opt in item.get("shippingOptions") or []:
            cost = opt.get("shippingCost")
            if cost and cost.get("value") is not None:
                c = _dec(cost["value"])
                if c is not None and (ship_cost is None or c < ship_cost):
                    ship_cost, ship_known = c, opt.get("shippingCostType") != "CALCULATED"
        loc = item.get("itemLocation") or {}
        options = item.get("buyingOptions") or []
        seller = item.get("seller") or {}
        images = [
            i["imageUrl"]
            for i in [item.get("image") or {}, *(item.get("additionalImages") or [])]
            if i.get("imageUrl")
        ]
        ends = None
        if item.get("itemEndDate"):
            try:
                ends = datetime.fromisoformat(item["itemEndDate"].replace("Z", "+00:00"))
            except ValueError:
                ends = None
        return RawListing(
            source=self.id,
            external_id=item.get("itemId", ""),
            url=item.get("itemWebUrl", ""),
            title=item.get("title", "")[:500],
            description=item.get("shortDescription"),
            price=_dec(price.get("value")),
            currency=price.get("currency", "CHF"),
            price_type="auction"
            if "AUCTION" in options and "FIXED_PRICE" not in options
            else ("negotiable" if "BEST_OFFER" in options else "fixed"),
            shipping_cost=ship_cost,
            shipping_known=ship_known,
            shipping_possible=bool(item.get("shippingOptions")) or None,
            pickup_possible=None,
            condition=_condition(item.get("conditionId"), item.get("condition")),
            condition_text=item.get("condition"),
            location_text=", ".join(
                x for x in (loc.get("postalCode"), loc.get("city"), loc.get("country")) if x
            )
            or None,
            postal_code=loc.get("postalCode"),
            country=loc.get("country"),
            seller={
                "name": seller.get("username"),
                "feedback_pct": seller.get("feedbackPercentage"),
                "feedback_count": seller.get("feedbackScore"),
            },
            images=images[:8],
            ends_at=ends,
            is_new_retail=False,
        )
