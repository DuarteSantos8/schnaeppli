from datetime import UTC, datetime
from decimal import Decimal

from app.services import geo, scoring
from app.services.schedule import next_daily
from app.sources.link import parse_page


def _assessment(**kw):
    base = {
        "relevance": "match",
        "condition": "good",
        "included_items": [],
        "requirement_misses": [],
        "red_flags": [],
        "market_value_low": 400,
        "market_value_high": 500,
        "market_confidence": "medium",
        "market_value_basis": "typical used asking prices",
        "injection_suspected": False,
    }
    return base | kw


def test_score_good_deal():
    r = scoring.score(_assessment(), Decimal("300"), Decimal("350"), [])
    assert r.label in ("exceptional", "good") and r.score >= 70
    assert r.market["source"] == "AI estimate (unverified)"


def test_score_overpriced_and_over_budget():
    r = scoring.score(_assessment(), Decimal("600"), Decimal("300"), [])
    assert r.label == "overpriced" and r.score < 40


def test_score_suspiciously_cheap_is_risky():
    r = scoring.score(_assessment(), Decimal("80"), Decimal("300"), [])
    assert r.label == "risky"


def test_injection_flag_makes_risky_and_irrelevant_unscored():
    assert scoring.score(_assessment(injection_suspected=True), Decimal("300"), None, []).label == "risky"
    assert scoring.score(_assessment(relevance="irrelevant"), Decimal("300"), None, []).score is None


def test_comparables_blend():
    r = scoring.score(_assessment(), Decimal("300"), None, [420, 450, 480, 500])
    assert r.market["comparables_n"] == 4 and "blended" in r.market["source"]
    assert r.market["kind"] == "asking_prices"


def test_low_confidence_pulls_to_middle():
    hi = scoring.score(_assessment(market_confidence="high"), Decimal("250"), None, [])
    lo = scoring.score(_assessment(market_confidence="low"), Decimal("250"), None, [])
    assert abs(lo.score - 50) < abs(hi.score - 50)


def test_effective_price():
    p, est = scoring.effective_price(Decimal("100"), Decimal("8"), True, True, False, None, "both")
    assert p == Decimal("108") and not est
    p, est = scoring.effective_price(Decimal("100"), None, False, True, False, None, "both")
    assert p == Decimal("109.00") and est
    p, est = scoring.effective_price(Decimal("100"), None, False, False, True, True, "both")
    assert p == Decimal("100") and not est


def test_schedule_timezone_and_dst():
    # 2026-03-29 is the spring DST switch in Zurich.
    after = datetime(2026, 3, 29, 4, 0, tzinfo=UTC)  # 06:00 local (CEST)
    nxt = next_daily(after, ["06:30", "17:30"], "Europe/Zurich")
    assert nxt == datetime(2026, 3, 29, 4, 30, tzinfo=UTC)
    winter = next_daily(datetime(2026, 1, 10, 6, 0, tzinfo=UTC), ["06:30"], "Europe/Zurich")
    assert winter == datetime(2026, 1, 11, 5, 30, tzinfo=UTC)
    # weekdays only
    sat = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    assert next_daily(sat, ["07:00"], "Europe/Zurich", [0, 1, 2, 3, 4]).weekday() == 0


def test_geo_bern_winterthur():
    r = geo.lookup_postcode("3011")
    assert r and r[2] == "Bern" and r[3] == "BE"
    w = geo.lookup_place("Winterthur")
    d = geo.haversine_km(r[0], r[1], w[0], w[1])
    assert 90 < d < 130


def test_link_jsonld_parse():
    page = """<html><head><title>x</title>
    <script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Sony Alpha 6400",
    "image":["https://img.example/a.jpg"],"description":"Body only",
    "offers":{"@type":"Offer","price":"649.00","priceCurrency":"CHF","itemCondition":"https://schema.org/NewCondition"}}
    </script></head></html>"""
    r = parse_page("https://www.galaxus.ch/en/s1/product/123", page)
    assert r.title == "Sony Alpha 6400" and r.price == Decimal("649.00") and r.currency == "CHF"
    assert r.source == "galaxus" and r.is_new_retail and r.condition == "new"
