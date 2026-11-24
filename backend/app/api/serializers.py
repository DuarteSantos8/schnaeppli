from __future__ import annotations

from decimal import Decimal

from app.api.images import proxied
from app.models import Analysis, Listing, SearchMatch, SearchProfile, SearchRun, WishlistItem


def num(v: Decimal | float | None) -> float | None:
    return float(v) if v is not None else None


def search_out(s: SearchProfile, stats: dict | None = None) -> dict:
    return {
        "id": str(s.id),
        "title": s.title,
        "prompt": s.prompt,
        "category": s.category,
        "spec": s.spec or {},
        "max_budget": num(s.max_budget),
        "currency": s.currency,
        "condition": s.condition,
        "prefer_condition": s.prefer_condition,
        "postal_code": s.postal_code,
        "radius_km": s.radius_km,
        "delivery": s.delivery,
        "sources": s.sources or {},
        "schedule": s.schedule or {},
        "notify": s.notify or {},
        "priority": s.priority,
        "status": s.status,
        "min_score": s.min_score,
        "parent_search_id": str(s.parent_search_id) if s.parent_search_id else None,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "last_error": s.last_error,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
        "stats": stats or {},
    }


def listing_out(listing: Listing) -> dict:
    return {
        "id": str(listing.id),
        "source": listing.source,
        "url": listing.url,
        "title": listing.title,
        "description": listing.description,
        "price": num(listing.price),
        "currency": listing.currency,
        "price_type": listing.price_type,
        "shipping_cost": num(listing.shipping_cost),
        "shipping_known": listing.shipping_known,
        "shipping_possible": listing.shipping_possible,
        "pickup_possible": listing.pickup_possible,
        "condition": listing.condition,
        "condition_text": listing.condition_text,
        "location_text": listing.location_text,
        "seller": listing.seller or {},
        "images": [p for p in (proxied(i) for i in (listing.images or [])) if p],
        "ends_at": listing.ends_at.isoformat() if listing.ends_at else None,
        "is_new_retail": listing.is_new_retail,
        "first_seen_at": listing.first_seen_at.isoformat(),
        "last_seen_at": listing.last_seen_at.isoformat(),
        "state": listing.state,
    }


def analysis_out(a: Analysis | None) -> dict | None:
    if a is None:
        return None
    return {
        "id": str(a.id),
        "kind": a.kind,
        "provider": a.provider,
        "model": a.model,
        "result": a.result or {},
        "score": a.score,
        "label": a.label,
        "breakdown": (a.score_breakdown or {}).get("items", []),
        "market_value": a.market_value or {},
        "created_at": a.created_at.isoformat(),
    }


def match_out(
    m: SearchMatch,
    listing: Listing,
    search: SearchProfile | None = None,
    analysis: Analysis | None = None,
    full: bool = False,
) -> dict:
    res = (analysis.result or {}) if analysis else {}
    out = {
        "id": str(m.id),
        "search_id": str(m.search_id),
        "search_title": search.title if search else None,
        "status": m.status,
        "relevance": m.relevance,
        "deal_score": m.deal_score,
        "deal_label": m.deal_label,
        "effective_price": num(m.effective_price),
        "effective_price_estimated": m.effective_price_estimated,
        "distance_km": m.distance_km,
        "within_radius": m.within_radius,
        "analysis_state": m.analysis_state,
        "skip_reason": m.skip_reason,
        "previous_price": num(m.previous_price),
        "price_dropped_at": m.price_dropped_at.isoformat() if m.price_dropped_at else None,
        "first_seen_at": m.first_seen_at.isoformat(),
        "summary": res.get("summary"),
        "identified_product": res.get("identified_product"),
        "market_mid": (analysis.market_value or {}).get("mid") if analysis else None,
        "red_flag_count": len(res.get("red_flags") or []),
        "note": m.note,
        "listing": listing_out(listing)
        if full
        else {
            "id": str(listing.id),
            "source": listing.source,
            "url": listing.url,
            "title": listing.title,
            "price": num(listing.price),
            "currency": listing.currency,
            "images": [p for p in (proxied(i) for i in (listing.images or [])[:1]) if p],
            "condition": listing.condition,
            "location_text": listing.location_text,
            "price_type": listing.price_type,
            "ends_at": listing.ends_at.isoformat() if listing.ends_at else None,
        },
    }
    if full:
        out["analysis"] = analysis_out(analysis)
    return out


def run_out(r: SearchRun) -> dict:
    return {
        "id": str(r.id),
        "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "status": r.status,
        "fetched": r.fetched,
        "new_matches": r.new_matches,
        "analyzed": r.analyzed,
        "source_report": r.source_report or {},
        "error": r.error,
    }


def wishlist_out(w: WishlistItem) -> dict:
    return {
        "id": str(w.id),
        "parent_id": str(w.parent_id) if w.parent_id else None,
        "title": w.title,
        "kind": w.kind,
        "category": w.category,
        "essential": w.essential,
        "budget": num(w.budget),
        "compatibility": w.compatibility or {},
        "status": w.status,
        "search_id": str(w.search_id) if w.search_id else None,
        "notes": w.notes,
        "sort": w.sort,
        "created_at": w.created_at.isoformat(),
    }
