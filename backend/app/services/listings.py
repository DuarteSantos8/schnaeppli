"""Listing upsert, deduplication, price history, and match creation."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.models import Listing, PricePoint, SearchMatch, SearchProfile, User
from app.services import geo, scoring
from app.sources.base import RawListing


def content_hash(r: RawListing) -> str:
    h = hashlib.sha256()
    for part in (
        r.title,
        r.description or "",
        str(r.price),
        str(r.shipping_cost),
        r.condition or "",
        *r.images[:3],
    ):
        h.update(part.encode())
        h.update(b"\x1f")
    return h.hexdigest()


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


async def upsert_listing(db: AsyncSession, r: RawListing) -> tuple[Listing, bool, Decimal | None]:
    """Insert or update. Returns (listing, is_new, previous_price)."""
    existing = await db.scalar(
        select(Listing).where(Listing.source == r.source, Listing.external_id == r.external_id)
    )
    now = utcnow()
    chash = content_hash(r)
    coords = geo.lookup_postcode(r.postal_code) if (r.country in (None, "CH")) else None
    if coords is None and r.location_text and (r.country in (None, "CH")):
        coords = geo.lookup_place(r.location_text)
    fields = dict(
        url=r.url,
        title=r.title,
        description=r.description,
        price=r.price,
        currency=r.currency,
        price_type=r.price_type,
        shipping_cost=r.shipping_cost,
        shipping_known=r.shipping_known,
        shipping_possible=r.shipping_possible,
        pickup_possible=r.pickup_possible,
        condition=r.condition,
        condition_text=r.condition_text,
        location_text=r.location_text,
        postal_code=r.postal_code,
        country=r.country,
        seller=r.seller,
        images=r.images,
        ends_at=r.ends_at,
        is_new_retail=r.is_new_retail,
        lat=coords[0] if coords else None,
        lon=coords[1] if coords else None,
    )
    if existing is None:
        listing = Listing(source=r.source, external_id=r.external_id, content_hash=chash, **fields)
        db.add(listing)
        await db.flush()
        if r.price is not None:
            db.add(PricePoint(listing_id=listing.id, price=r.price, shipping_cost=r.shipping_cost))
        return listing, True, None

    previous = existing.price
    existing.last_seen_at = now
    existing.state = "active"
    if existing.content_hash != chash:
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.content_hash = chash
        if existing.identity.get("hash") != chash:
            existing.identity = {}
    if r.price is not None and previous != r.price:
        db.add(PricePoint(listing_id=existing.id, price=r.price, shipping_cost=r.shipping_cost))
    return existing, False, previous


def prefilter(search: SearchProfile, listing: Listing) -> str | None:
    """Cheap rule-based filter before any AI cost. Returns a skip reason or None."""
    title = _norm_title(listing.title)
    spec = search.spec or {}
    for word in spec.get("excluded", []):
        w = _norm_title(word)
        if w and re.search(rf"\b{re.escape(w)}\b", title):
            return f"excluded keyword: {word}"
    if re.search(r"\b(suche|gesucht|wanted|cherche|wtb)\b", title):
        return "looks like a 'wanted' ad"
    if search.condition == "new" and listing.condition in ("used", "for_parts"):
        return "condition: you only want new"
    if search.condition == "used" and listing.condition == "new" and not listing.is_new_retail:
        pass  # still interesting: new items can be deals in second-hand searches
    if listing.condition == "for_parts" and "defekt" not in (search.prompt or "").lower():
        return "sold for parts / not working"
    if (
        search.max_budget is not None
        and listing.price is not None
        and listing.price > search.max_budget * Decimal("1.25")
    ):
        return "well over budget"
    return None


def location_facts(user: User, search: SearchProfile, listing: Listing) -> tuple[float | None, bool | None]:
    lat, lon = user.lat, user.lon
    if search.postal_code:
        c = geo.lookup_postcode(search.postal_code)
        if c:
            lat, lon = c[0], c[1]
    if lat is None or listing.lat is None:
        return None, None
    d = geo.road_estimate_km(geo.haversine_km(lat, lon, listing.lat, listing.lon))
    radius = search.radius_km or user.radius_km
    return round(d, 1), d <= radius


async def ensure_match(
    db: AsyncSession, user: User, search: SearchProfile, listing: Listing, previous_price: Decimal | None
) -> tuple[SearchMatch, bool]:
    match = await db.scalar(
        select(SearchMatch).where(SearchMatch.search_id == search.id, SearchMatch.listing_id == listing.id)
    )
    distance, within = location_facts(user, search, listing)
    delivery = search.delivery or user.delivery
    eff, est = scoring.effective_price(
        listing.price,
        listing.shipping_cost,
        listing.shipping_known,
        listing.shipping_possible,
        listing.pickup_possible,
        within,
        delivery,
    )
    created = False
    if match is None:
        reason = prefilter(search, listing)
        match = SearchMatch(
            user_id=user.id,
            search_id=search.id,
            listing_id=listing.id,
            analysis_state="skipped" if reason else "queued",
            relevance="irrelevant" if reason else "pending",
            skip_reason=reason,
        )
        db.add(match)
        created = True
    elif previous_price is not None and listing.price is not None and listing.price < previous_price:
        match.previous_price = previous_price
        match.price_dropped_at = utcnow()
    match.distance_km = distance
    match.within_radius = within
    match.effective_price = eff
    match.effective_price_estimated = est
    return match, created
