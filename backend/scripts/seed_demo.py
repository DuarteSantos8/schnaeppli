"""Seed a DEVELOPMENT database with demo data for screenshots and UI work.

Refuses to run in production. Listing photos are openly licensed pictures from
Wikimedia Commons (credits in docs/screenshots/CREDITS.md); the listings,
prices and analyses are invented and are not real offers.

    SCHNAEPPLI_ENV=development SCHNAEPPLI_DATABASE_URL=sqlite+aiosqlite:///demo.db python -m scripts.seed_demo
"""

from __future__ import annotations

import asyncio
import random
from datetime import timedelta
from decimal import Decimal

from app.core.config import get_settings
from app.core.db import Base, get_engine, sessionmaker, utcnow
from app.core.security import hash_password
from app.models import (
    AIUsage,
    Analysis,
    Listing,
    PricePoint,
    Purchase,
    SearchMatch,
    SearchProfile,
    SearchRun,
    User,
    WishlistItem,
)
from app.services import scoring

C = "https://thumb.wikimedia.org/wikipedia/commons/thumb"
IMG = {
    "sigma_a6000": f"{C}/f/ff/Sigma_30mm_F1.4_DC_DN_Contemporary_with_lens_cap_on_Sony_Alpha_6000.jpg/1280px-Sigma_30mm_F1.4_DC_DN_Contemporary_with_lens_cap_on_Sony_Alpha_6000.jpg",
    "sigma30": f"{C}/d/d4/Sigma_30mm_F1.4_C.jpg/1280px-Sigma_30mm_F1.4_C.jpg",
    "m50ii": f"{C}/c/c9/Canon_EOS_M50_Mark_II_2.jpg/1280px-Canon_EOS_M50_Mark_II_2.jpg",
    "m50": f"{C}/4/4e/Canon_EOS_M50_black_01.jpg/1280px-Canon_EOS_M50_black_01.jpg",
    "qx100": f"{C}/7/76/Sony_DSC_QX100.jpg/1280px-Sony_DSC_QX100.jpg",
    "ds223j": f"{C}/f/fb/Synology_Disk_Station_DS223J_-_NAS-Server.jpg/1280px-Synology_Disk_Station_DS223J_-_NAS-Server.jpg",
    "rtx3070": f"{C}/b/b9/MSI_GeForce_RTX_3070_VENTUS_3X_OC.jpg/1280px-MSI_GeForce_RTX_3070_VENTUS_3X_OC.jpg",
    "emount": f"{C}/9/9c/Taipei_IT_Month_Sony_E-mount_lens_lineup_20131202.jpg/1280px-Taipei_IT_Month_Sony_E-mount_lens_lineup_20131202.jpg",
}


def spec(products, alternatives=(), queries=(), must=(), excluded=("defekt",)):
    return {
        "desired_products": [{"name": p} for p in products],
        "alternatives": [{"name": a, "reason": r} for a, r in alternatives],
        "allow_alternatives": bool(alternatives),
        "excluded": list(excluded), "preferred_brands": [], "accessories": [], "must_have": list(must),
        "nice_to_have": [], "queries": list(queries), "notes": None,
    }


def assessment(product, rel, cond, lo, hi, summary, facts, assumptions, flags=(), extras=(), conf="medium"):
    return {
        "relevance": rel, "identified_product": product, "requirement_matches": [], "requirement_misses": [],
        "condition": cond, "included_items": list(extras), "facts": list(facts), "assumptions": list(assumptions),
        "red_flags": [{"type": t, "detail": d} for t, d in flags], "market_value_low": lo, "market_value_high": hi,
        "market_value_basis": "typical asking prices for used units in Switzerland and Germany",
        "market_confidence": conf, "alternative_reason": None, "possibly_undervalued": False, "summary": summary,
        "worth_deep_look": False, "injection_suspected": False,
    }


async def main() -> None:
    s = get_settings()
    if s.env == "production":
        raise SystemExit("Refusing to seed demo data into a production instance.")
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    now = utcnow()
    rnd = random.Random(7)  # noqa: S311 (demo data, not security)
    async with sessionmaker()() as db:
        user = User(email="demo@example.com", display_name="Alex", password_hash=hash_password("schnaeppli-demo-pass"),
                    is_admin=True, postal_code="8001", city="Zürich", lat=47.3721, lon=8.5419, radius_km=50,
                    monthly_budget=Decimal("600"), last_digest_at=now - timedelta(hours=9))
        db.add(user)
        await db.flush()

        cam = SearchProfile(user_id=user.id, title="Mirrorless camera under CHF 300", category="Cameras",
                            prompt="A digital camera under CHF 300. I like vintage Sony Cyber-shots, but an Alpha 6400 or something comparable would also work.",
                            spec=spec(["Sony Alpha 6400", "Sony Cyber-shot RX100 III"],
                                      [("Canon EOS M50", "Similar APS-C sensor and size, often cheaper used"),
                                       ("Sony Alpha 6000", "Older sibling of the a6400, same lens mount"),
                                       ("Fujifilm X-T30", "Comparable sensor, great colours, usually a bit pricier")],
                                      ["a6400", "ILCE-6400", "rx100 iii", "eos m50", "a6000"]),
                            max_budget=Decimal("300"), condition="any", priority=1,
                            last_run_at=now - timedelta(hours=3), next_run_at=now + timedelta(hours=5))
        lens = SearchProfile(user_id=user.id, title="Sony E-mount lens under CHF 200", category="Lenses",
                             prompt="Sony E-mount lenses, preferably Sigma or Sony, under CHF 200.",
                             spec=spec(["Sigma 30mm f/1.4 DC DN"], [("Sony E 35mm f/1.8 OSS", "Fast prime for the same mount")],
                                       ["sigma 30mm 1.4 sony e", "sel35f18"], ["Sony E-mount"]),
                             max_budget=Decimal("200"), condition="used",
                             last_run_at=now - timedelta(hours=3), next_run_at=now + timedelta(hours=5))
        nas = SearchProfile(user_id=user.id, title="NAS with 4 drive bays", category="Storage",
                            prompt="A good NAS with at least four drive bays.",
                            spec=spec(["Synology DS920+", "Synology DS423+"], [("QNAP TS-464", "4 bays, 2.5 GbE")],
                                      ["ds920+", "ds423+", "ts-464"], ["4 drive bays"]),
                            max_budget=Decimal("450"), last_run_at=now - timedelta(hours=3),
                            next_run_at=now + timedelta(hours=5))
        gpu = SearchProfile(user_id=user.id, title="RTX 4070 Ti Super or better", category="Graphics cards",
                            prompt="Find me an RTX 4070 Ti Super or better for less than CHF 600.",
                            spec=spec(["RTX 4070 Ti Super", "RTX 4080"], [], ["4070 ti super", "rtx 4080"]),
                            max_budget=Decimal("600"), status="paused")
        db.add_all([cam, lens, nas, gpu])
        await db.flush()

        rows = [
            (cam, "ebay", "Sony Alpha 6000 + Sigma 30mm f/1.4, top Zustand", 345, 9, [IMG["sigma_a6000"]],
             assessment("Sony Alpha 6000", "bundle", "good", 330, 420, "Camera and a fast Sigma prime for less than the two usually cost separately.",
                        ["Body + Sigma 30mm f/1.4 DC DN", "Charger and 2 batteries included", "About 9,000 shutter actuations"],
                        ["The lens alone usually sells for around CHF 200 used"], extras=["Sigma 30mm f/1.4", "2 batteries"]), "8400", "Winterthur"),
            (cam, "ebay", "Canon EOS M50 Mark II Body, wie neu, OVP", 289, 0, [IMG["m50ii"]],
             assessment("Canon EOS M50 Mark II", "alternative", "like_new", 330, 400, "Almost new M50 II well under typical used prices.",
                        ["Original box", "Bought 2025, invoice available"], ["No lens included"]), "8048", "Zürich"),
            (cam, "ebay", "Canon EOS M50 schwarz mit 15-45mm", 260, 12, [IMG["m50"]],
             assessment("Canon EOS M50", "alternative", "good", 280, 340, "Fair price for the kit with the 15-45mm lens.",
                        ["Kit lens 15-45mm", "Small scratch on the screen"], ["Shutter count not stated"],
                        flags=[("incomplete_description", "Battery condition not mentioned")]), "3011", "Bern"),
            (cam, "ebay", "Sony DSC-QX100 Objektivkamera", 95, 9, [IMG["qx100"]],
             assessment("Sony DSC-QX100", "alternative", "fair", 90, 140, "Quirky lens-style camera; only works with a phone app.",
                        ["Works with smartphone app"], ["App support may be discontinued"],
                        flags=[("other", "Needs a smartphone, no screen of its own")], conf="low"), "6003", "Luzern"),
            (lens, "ebay", "Sigma 30mm F1.4 DC DN Contemporary Sony E", 165, 7, [IMG["sigma30"]],
             assessment("Sigma 30mm f/1.4 DC DN", "match", "good", 190, 230, "Good price for the lens you asked for, with hood.",
                        ["Lens hood and both caps", "No scratches on the glass"], ["Firmware version unknown"]), "8305", "Dietlikon"),
            (lens, "galaxus", "Sony E 35mm F1.8 OSS (neu)", 329, 0, [IMG["emount"]],
             assessment("Sony E 35mm f/1.8 OSS", "alternative", "new", 300, 350, "New from a shop, but over your CHF 200 budget.",
                        ["New, 2-year warranty"], []), None, None),
            (nas, "ebay", "Synology DS223j NAS 2-Bay", 135, 10, [IMG["ds223j"]],
             assessment("Synology DS223j", "irrelevant", "good", 150, 180, "Only two drive bays; you need four.",
                        ["2 bays"], [], flags=[("incompatible", "2 drive bays, search requires 4")]), "4051", "Basel"),
            (gpu, "ebay", "MSI GeForce RTX 3070 Ventus 3X OC", 280, 12, [IMG["rtx3070"]],
             assessment("RTX 3070", "irrelevant", "good", 260, 320, "Older and slower than a 4070 Ti Super.",
                        [], [], flags=[("other", "Below the requested performance class")]), "8400", "Winterthur"),
        ]
        for i, (search, src, title, price, ship, imgs, res, plz, city) in enumerate(rows):
            listing = Listing(source=src, external_id=f"demo-{i}", url=f"https://example.com/demo/{i}", title=title,
                              description="Demo listing for screenshots. Not a real offer.", price=Decimal(price),
                              currency="CHF", shipping_cost=Decimal(ship) if ship else None, shipping_known=bool(ship),
                              shipping_possible=True, pickup_possible=plz is not None, condition="new" if src == "galaxus" else "used",
                              location_text=f"{plz} {city}" if plz else None, postal_code=plz, country="CH",
                              images=imgs, content_hash=f"h{i}", is_new_retail=src == "galaxus",
                              seller={"name": f"seller{i}", "feedback_pct": "99.6", "feedback_count": 120 + i * 37},
                              first_seen_at=now - timedelta(hours=rnd.randint(1, 60)))
            if plz:
                from app.services import geo

                c = geo.lookup_postcode(plz)
                listing.lat, listing.lon = (c[0], c[1]) if c else (None, None)
            db.add(listing)
            await db.flush()
            first = Decimal(price + (30 if i in (0, 4) else 0))
            db.add(PricePoint(listing_id=listing.id, price=first, observed_at=listing.first_seen_at))
            if first != Decimal(price):
                db.add(PricePoint(listing_id=listing.id, price=Decimal(price), observed_at=now - timedelta(hours=2)))
            dist = None
            if listing.lat:
                from app.services import geo

                dist = round(geo.road_estimate_km(geo.haversine_km(user.lat, user.lon, listing.lat, listing.lon)), 1)
            eff = Decimal(price + (ship or 9))
            sc = scoring.score(res, eff, search.max_budget, [], within_radius=dist is not None and dist <= 50)
            a = Analysis(user_id=user.id, listing_id=listing.id, search_id=search.id, kind="quick_scan", input_hash=f"x{i}",
                         provider="anthropic", model="claude-opus-5-5", result=res, score=sc.score, label=sc.label,
                         score_breakdown={"items": sc.breakdown}, market_value=sc.market)
            db.add(a)
            await db.flush()
            db.add(SearchMatch(user_id=user.id, search_id=search.id, listing_id=listing.id, status="new" if i in (1, 4) else "seen",
                               relevance=res["relevance"], deal_score=sc.score, deal_label=sc.label, effective_price=eff,
                               effective_price_estimated=not ship, distance_km=dist, within_radius=dist is not None and dist <= 50,
                               analysis_id=a.id, analysis_state="done", first_seen_at=listing.first_seen_at,
                               previous_price=first if first != Decimal(price) else None,
                               price_dropped_at=now - timedelta(hours=2) if first != Decimal(price) else None))
        for search in (cam, lens, nas):
            for h in (3, 15, 27):
                db.add(SearchRun(search_id=search.id, started_at=now - timedelta(hours=h), finished_at=now - timedelta(hours=h, seconds=-40),
                                 status="ok", fetched=rnd.randint(30, 90), new_matches=rnd.randint(0, 4)))
        # Wishlist with accessories
        body = WishlistItem(user_id=user.id, title="Sony Alpha 6400", budget=Decimal("650"), compatibility={"mount": "Sony E", "battery": "NP-FW50"})
        db.add(body)
        await db.flush()
        db.add_all([
            WishlistItem(user_id=user.id, parent_id=body.id, kind="accessory", title="Sigma 30mm f/1.4", budget=Decimal("200"), essential=True, compatibility={"mount": "Sony E"}, search_id=lens.id),
            WishlistItem(user_id=user.id, parent_id=body.id, kind="accessory", title="Spare batteries (2x)", budget=Decimal("40"), compatibility={"battery": "NP-FW50"}),
            WishlistItem(user_id=user.id, parent_id=body.id, kind="accessory", title="SD card 128 GB V30", budget=Decimal("25")),
            WishlistItem(user_id=user.id, parent_id=body.id, kind="accessory", title="Camera bag", budget=Decimal("60")),
            WishlistItem(user_id=user.id, title="NAS with 4 drive bays", budget=Decimal("450"), search_id=nas.id),
        ])
        month = now.strftime("%Y-%m")
        db.add_all([
            Purchase(user_id=user.id, title="USB-C hub", amount=Decimal("39.90"), category="Accessories", status="purchased", month=month),
            Purchase(user_id=user.id, title="Sigma 30mm F1.4 DC DN Contemporary Sony E", amount=Decimal("172"), category="Lenses", status="planned", month=month),
        ])
        for d in range(30):
            for _ in range(rnd.randint(2, 9)):
                kind = rnd.choice(["quick_scan"] * 6 + ["vision_analysis", "deep_analysis", "chat", "digest_generation"])
                i, o = rnd.randint(1800, 3500), rnd.randint(350, 900)
                db.add(AIUsage(user_id=user.id, credential_scope="byok", provider="anthropic", model="claude-opus-5-5", kind=kind,
                               search_id=rnd.choice([cam.id, lens.id, nas.id]), input_tokens=i, output_tokens=o,
                               cost_usd=Decimal(str(round(i * 4 / 1e6 + o * 20 / 1e6, 6))), created_at=now - timedelta(days=d, hours=rnd.randint(0, 12))))
        await db.commit()
    print("Seeded demo data. Sign in as demo@example.com / schnaeppli-demo-pass")


if __name__ == "__main__":
    asyncio.run(main())
