"""Deal Score (0–100): deterministic and explainable.

The AI supplies structured facts and a market-value *estimate*; this module turns
them into a score with an itemized breakdown. Keeping the arithmetic in code
means a listing can't talk its way into a high score, and every point shown in
the UI can be explained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median

LABELS = ("exceptional", "good", "fair", "overpriced", "risky")
SWISS_PARCEL_ESTIMATE = Decimal("9.00")  # typical Swiss Post parcel price, shown as an estimate

CONDITION_ADJ = {"new": 5, "like_new": 3, "good": 0, "fair": -8, "poor": -15, "defective": -30, "unknown": -4}
FLAG_ADJ = {
    "possible_defect": -10,
    "seller_risk": -10,
    "incomplete_description": -5,
    "poor_title": 0,
    "misclassified": 0,
    "suspicious_price": -8,
    "wanted_ad": -40,
    "incompatible": -40,
    "other": -4,
}


@dataclass
class ScoreResult:
    score: int | None
    label: str | None
    breakdown: list[dict] = field(default_factory=list)
    market: dict = field(default_factory=dict)


def effective_price(
    price: Decimal | None,
    shipping_cost: Decimal | None,
    shipping_known: bool,
    shipping_possible: bool | None,
    pickup_possible: bool | None,
    within_radius: bool | None,
    delivery_pref: str,
) -> tuple[Decimal | None, bool]:
    """Price the user would actually pay. Returns (amount, is_estimate)."""
    if price is None:
        return None, True
    pickup_ok = pickup_possible and within_radius and delivery_pref in ("pickup", "both")
    if pickup_ok and (delivery_pref == "pickup" or not shipping_possible):
        return price, within_radius is None
    if shipping_cost is not None:
        return price + shipping_cost, not shipping_known
    if shipping_possible is False and pickup_ok:
        return price, False
    return price + SWISS_PARCEL_ESTIMATE, True


def _price_points(ratio: float) -> float:
    if ratio <= 0.6:
        return 100
    if ratio <= 1.0:
        return 100 - (ratio - 0.6) / 0.4 * 45  # 100 → 55
    if ratio <= 1.3:
        return 55 - (ratio - 1.0) / 0.3 * 40  # 55 → 15
    return 5


def market_estimate(ai: dict, comparables: list[float]) -> dict:
    """Blend the AI range with asking prices of comparable listings Schnäppli has seen."""
    low, high = ai.get("market_value_low"), ai.get("market_value_high")
    ai_mid = (low + high) / 2 if low and high else (low or high)
    comps = [c for c in comparables if c and c > 0]
    out = {
        "ai_low": low,
        "ai_high": high,
        "ai_basis": ai.get("market_value_basis"),
        "ai_confidence": ai.get("market_confidence", "low"),
        "comparables_n": len(comps),
        "comparables_median": round(median(comps), 2) if comps else None,
        "kind": "asking_prices",  # never completed sales: no source here provides those
    }
    if len(comps) >= 3 and ai_mid:
        out["mid"] = round(0.5 * ai_mid + 0.5 * median(comps), 2)
        out["source"] = f"AI estimate blended with {len(comps)} comparable asking prices"
        out["confidence"] = "medium" if out["ai_confidence"] == "low" else out["ai_confidence"]
    elif len(comps) >= 3:
        out["mid"] = round(median(comps), 2)
        out["source"] = f"median of {len(comps)} comparable asking prices"
        out["confidence"] = "medium" if len(comps) >= 6 else "low"
    elif ai_mid:
        out["mid"] = round(ai_mid, 2)
        out["source"] = "AI estimate (unverified)"
        out["confidence"] = out["ai_confidence"]
    else:
        out["mid"] = None
        out["source"] = "no reliable estimate"
        out["confidence"] = "none"
    return out


def score(
    assessment: dict,
    eff_price: Decimal | None,
    max_budget: Decimal | None,
    comparables: list[float],
    *,
    within_radius: bool | None = None,
    pickup_only: bool = False,
    learned_adjustment: float = 0.0,
    vision: dict | None = None,
) -> ScoreResult:
    b: list[dict] = []

    def add(label: str, pts: float, kind: str = "adjustment") -> None:
        if pts:
            b.append({"label": label, "points": round(pts, 1), "kind": kind})

    rel = assessment.get("relevance")
    if rel == "irrelevant":
        return ScoreResult(
            None, None, [{"label": "Not relevant to this search", "points": 0, "kind": "info"}]
        )

    market = market_estimate(assessment, comparables)
    risky_reasons: list[str] = []
    if eff_price is None:
        risky_reasons.append("no price given")
        base = 40.0
    elif not market.get("mid"):
        risky_reasons.append("no reliable market value")
        base = 45.0
    else:
        ratio = float(eff_price) / float(market["mid"])
        base = _price_points(ratio)
        market["ratio"] = round(ratio, 3)
        if ratio < 0.45:
            risky_reasons.append("price far below market value (possible scam or defect)")
    add("Price vs. market value", base, "base")
    total = base

    cond = assessment.get("condition", "unknown")
    total += CONDITION_ADJ.get(cond, 0)
    add(f"Condition: {cond.replace('_', ' ')}", CONDITION_ADJ.get(cond, 0))

    if rel == "alternative":
        total -= 4
        add("Alternative, not a first choice", -4)
    if rel == "bundle" and assessment.get("included_items"):
        total += 5
        add("Bundle with extras", 5)

    misses = len(assessment.get("requirement_misses") or [])
    if misses:
        pts = -min(15, misses * 5)
        total += pts
        add(f"{misses} requirement(s) not met or unknown", pts)

    flag_pts = 0
    for f in assessment.get("red_flags") or []:
        flag_pts += FLAG_ADJ.get(f.get("type"), -4)
        if f.get("type") in ("wanted_ad", "incompatible"):
            risky_reasons.append(f.get("detail") or f.get("type"))
    flag_pts = max(flag_pts, -45)
    if flag_pts:
        total += flag_pts
        add("Red flags", flag_pts)
    if len(assessment.get("red_flags") or []) >= 3:
        risky_reasons.append("several red flags")

    if vision:
        issues = [i for i in vision.get("possible_issues", []) if i.get("confidence") in ("medium", "high")]
        if issues:
            pts = -min(15, 5 * len(issues))
            total += pts
            add("Possible issues visible in photos", pts)
        if vision.get("looks_like_stock_photo"):
            total -= 3
            add("Only stock photos", -3)

    if max_budget is not None and eff_price is not None and eff_price > max_budget:
        over = float(eff_price / max_budget) - 1
        pts = -min(30, 10 + over * 100)
        total += pts
        add("Over your budget", pts)

    if pickup_only and within_radius is False:
        total -= 25
        add("Pickup only, outside your radius", -25)

    if learned_adjustment:
        total += learned_adjustment
        add("Learned from your feedback", learned_adjustment)

    if market.get("confidence") in ("low", "none"):
        pulled = total + (50 - total) * 0.3
        add("Low confidence in market value", pulled - total)
        total = pulled

    if assessment.get("injection_suspected"):
        risky_reasons.append("listing text tried to manipulate the assessment")

    final = int(max(0, min(100, round(total))))
    if risky_reasons:
        label = "risky"
        b.append({"label": "Risky: " + "; ".join(risky_reasons), "points": 0, "kind": "info"})
    elif final >= 85:
        label = "exceptional"
    elif final >= 70:
        label = "good"
    elif final >= 50:
        label = "fair"
    else:
        label = "overpriced"
    return ScoreResult(final, label, b, market)
