"""Learning from feedback, transparently.

Every favorite / reject / purchase nudges a handful of named weights. They're
shown verbatim in Settings → Learned preferences and can be reset. They only
adjust ranking by at most ±10 points; they never hide listings. Nothing leaves
the instance.
"""

from __future__ import annotations

from app.models import Analysis, Listing, SearchMatch, User

POSITIVE = {"favorite": 1.0, "interested": 0.6, "planned": 0.8, "purchased": 1.5}
NEGATIVE = {"rejected": -1.0}
STEP = 0.15
CAP = 1.0


def _features(match: SearchMatch, listing: Listing, analysis: Analysis | None) -> list[str]:
    feats = []
    res = (analysis.result if analysis else {}) or {}
    rel = res.get("relevance") or match.relevance
    if rel:
        feats.append(f"relevance:{rel}")
    cond = res.get("condition") or listing.condition
    if cond:
        feats.append(f"condition:{cond}")
    if res.get("included_items"):
        feats.append("has:extras")
    if listing.pickup_possible and not listing.shipping_possible:
        feats.append("delivery:pickup_only")
    if listing.price_type == "auction":
        feats.append("format:auction")
    mv = (analysis.market_value if analysis else {}) or {}
    ratio = mv.get("ratio")
    if ratio is not None:
        feats.append(
            "price:below_market"
            if ratio < 0.9
            else "price:above_market"
            if ratio > 1.05
            else "price:at_market"
        )
    return feats


def apply_feedback(
    user: User, match: SearchMatch, listing: Listing, analysis: Analysis | None, status: str
) -> None:
    signal = POSITIVE.get(status) or NEGATIVE.get(status)
    if not signal:
        return
    prefs = dict(user.learned_prefs or {})
    weights = dict(prefs.get("weights", {}))
    for f in _features(match, listing, analysis):
        w = weights.get(f, 0.0) + STEP * signal
        weights[f] = round(max(-CAP, min(CAP, w)), 3)
    prefs["weights"] = weights
    prefs["signals"] = int(prefs.get("signals", 0)) + 1
    user.learned_prefs = prefs


def adjustment(user: User, match: SearchMatch, listing: Listing, analysis: Analysis | None) -> float:
    prefs = user.learned_prefs or {}
    if prefs.get("signals", 0) < 3:  # need a few signals before it matters
        return 0.0
    weights = prefs.get("weights", {})
    total = sum(weights.get(f, 0.0) for f in _features(match, listing, analysis))
    return round(max(-10.0, min(10.0, total * 5)), 1)


def explain(user: User) -> list[dict]:
    weights = (user.learned_prefs or {}).get("weights", {})
    names = {
        "relevance:bundle": "Bundles",
        "relevance:alternative": "Alternatives",
        "relevance:accessory": "Accessories",
        "relevance:match": "Exact matches",
        "has:extras": "Listings with extras",
        "format:auction": "Auctions",
        "delivery:pickup_only": "Pickup-only listings",
        "price:below_market": "Below market value",
        "price:above_market": "Above market value",
        "price:at_market": "Around market value",
    }
    out = []
    for k, w in sorted(weights.items(), key=lambda kv: -abs(kv[1])):
        if abs(w) < 0.05:
            continue
        label = names.get(k) or k.split(":", 1)[-1].replace("_", " ").capitalize()
        out.append({"key": k, "label": label, "weight": w, "direction": "likes" if w > 0 else "dislikes"})
    return out
