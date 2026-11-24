"""User-added shops: address handling, robots.txt, product data, blocks, search runs."""

import uuid

import httpx
import pytest
import respx
from sqlalchemy import select

from app.core import safe_http
from app.core.db import sessionmaker
from app.core.safe_http import Robots
from app.models import CustomShop, Listing
from app.services.runner import run_search
from app.sources import shops


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    async def public(host):
        return None

    monkeypatch.setattr(safe_http, "_assert_public", public)
    monkeypatch.setattr(shops, "HOST_GAP", 0)
    safe_http._robots_cache.clear()
    shops._cache.clear()


SEARCH_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"ItemList","itemListElement":[
 {"@type":"ListItem","position":1,"item":{"@type":"Product","name":"Olympus OM-1 Gehäuse",
   "url":"/p/om1","image":"https://cdn.fotoshop.ch/om1.jpg",
   "offers":{"@type":"Offer","price":"249.00","priceCurrency":"CHF","itemCondition":"https://schema.org/UsedCondition"}}},
 {"@type":"ListItem","position":2,"item":{"@type":"Product","name":"Kamera-Tasche",
   "url":"/p/bag","offers":{"@type":"Offer","price":"39","priceCurrency":"CHF"}}}
]}</script></head><body></body></html>"""

MICRODATA = """<div itemscope itemtype="https://schema.org/Product">
  <a itemprop="url" href="/p/x100"><h2 itemprop="name">Fujifilm <b>X100</b> silber</h2></a>
  <img itemprop="image" src="https://img.shop.ch/x100.jpg">
  <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
    <meta itemprop="priceCurrency" content="CHF"><span itemprop="price">CHF 1'190.–</span>
  </div>
</div>"""


def test_template_from_search_page_homepage_and_placeholder():
    t = shops.template_from("https://www.fotoshop.ch/suche?q=olympus+om1&sort=price")
    assert t.mode == "page" and t.example == "olympus om1"
    assert t.url == "https://www.fotoshop.ch/suche?q={query}&sort=price"
    assert shops.fill(t.url, "leica m6") == "https://www.fotoshop.ch/suche?q=leica+m6&sort=price"
    w = shops.template_from("kameras-shop.ch")
    assert w.mode == "woo" and w.url.startswith(
        "https://kameras-shop.ch/wp-json/wc/store/v1/products?search="
    )
    p = shops.template_from("https://shop.ch/search/{query}")
    assert shops.fill(p.url, "leica m6") == "https://shop.ch/search/leica%20m6"
    with pytest.raises(ValueError):
        shops.template_from("https://shop.ch/kategorie/kameras")


def test_robots_wildcards_and_longest_match():
    r = Robots("User-agent: *\nDisallow: /*?*q=\nAllow: /suche?q=\n\nUser-agent: GPTBot\nDisallow: /\n")
    assert not r.allows("https://x/list?page=2&q=a")
    assert r.allows("https://x/suche?q=a")  # the longer Allow wins
    own = Robots("User-agent: SchnaeppliBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert not own.allows("https://x/anything")


def test_parse_jsonld_microdata_and_woo():
    items = shops.items_from_jsonld(SEARCH_PAGE, "https://www.fotoshop.ch/suche?q=x")
    assert [i.title for i in items] == ["Olympus OM-1 Gehäuse", "Kamera-Tasche"]
    assert items[0].url == "https://www.fotoshop.ch/p/om1" and str(items[0].price) == "249.00"
    raw = shops.to_raw("fotoshop.ch", "retail", items[0])
    assert raw.condition == "used" and not raw.is_new_retail and raw.images

    (m,) = shops.items_from_microdata(MICRODATA, "https://shop.ch/s?q=x")
    assert m.title == "Fujifilm X100 silber" and m.url == "https://shop.ch/p/x100"
    assert str(m.price) == "1190" and m.image == "https://img.shop.ch/x100.jpg"

    woo = [{"id": 5, "name": "Leica M6 &amp; Objektiv", "permalink": "https://k.ch/p/m6",
            "prices": {"price": "245000", "currency_code": "CHF", "currency_minor_unit": 2},
            "images": [{"src": "https://k.ch/m6.jpg"}], "short_description": "<p>Top</p>"}]  # fmt: skip
    (w,) = shops.items_from_woo(woo, "https://k.ch")
    assert w.title == "Leica M6 & Objektiv" and str(w.price) == "2450" and w.description == "Top"


@respx.mock
async def test_add_shop_tests_it_and_shows_a_preview(alice):
    respx.get("https://www.fotoshop.ch/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /")
    )
    respx.get(url__startswith="https://www.fotoshop.ch/suche").mock(
        return_value=httpx.Response(200, text=SEARCH_PAGE)
    )
    r = await alice.post("/api/shops", json={"address": "https://www.fotoshop.ch/suche?q=olympus"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert (
        body["shop"]["state"] == "ok"
        and body["shop"]["host"] == "fotoshop.ch"
        and body["shop"]["name"] == "Fotoshop"
    )
    assert body["preview"][0]["price"] == 249.0
    again = await alice.post("/api/shops", json={"address": "fotoshop.ch/suche?q=x"})
    assert again.status_code == 409
    assert (await alice.get("/api/shops")).json()[0]["enabled"] is True


@respx.mock
async def test_bot_check_and_robots_are_respected(alice):
    respx.get("https://blocked.ch/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(url__startswith="https://blocked.ch/s").mock(
        return_value=httpx.Response(200, text="<title>Kurze Prüfung</title> Bitte bestätigen")
    )
    respx.get("https://closed.ch/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /*?q=")
    )
    page = respx.get(url__startswith="https://closed.ch/s")
    b = (await alice.post("/api/shops", json={"address": "https://blocked.ch/s?q=a"})).json()["shop"]
    c = (await alice.post("/api/shops", json={"address": "https://closed.ch/s?q=a"})).json()["shop"]
    assert b["state"] == "blocked" and c["state"] == "robots"
    assert not page.called  # robots.txt said no: the page is never fetched


async def test_built_in_and_forbidden_sites_are_refused(alice):
    r = await alice.post("/api/shops", json={"address": "https://www.amazon.de/s?k=kamera"})
    assert r.status_code == 422 and "Amazon" in r.json()["detail"]
    r = await alice.post("/api/shops", json={"address": "https://www.galaxus.ch/search?q=x"})
    assert r.status_code == 422


@respx.mock
async def test_search_run_asks_the_users_shops(alice, monkeypatch):
    from app.sources import galaxus

    async def nothing(self, q):
        return []

    monkeypatch.setattr(galaxus.GalaxusAdapter, "search", nothing)
    respx.get("https://www.fotoshop.ch/robots.txt").mock(return_value=httpx.Response(200, text=""))
    route = respx.get(url__startswith="https://www.fotoshop.ch/suche").mock(
        return_value=httpx.Response(200, text=SEARCH_PAGE)
    )
    await alice.post(
        "/api/shops", json={"address": "https://www.fotoshop.ch/suche?q=olympus", "kind": "secondhand"}
    )
    s = (await alice.post("/api/searches", json={"title": "Olympus OM-1", "max_budget": 400})).json()
    async with sessionmaker()() as db:
        run, _ = await run_search(db, uuid.UUID(s["id"]))
        assert run.source_report["fotoshop.ch"]["results"] == 1  # the bag isn't an OM-1
        (lst,) = (await db.scalars(select(Listing).where(Listing.source == "fotoshop.ch"))).all()
        assert lst.title.startswith("Olympus") and lst.condition == "used"
        shop = (await db.scalars(select(CustomShop))).one()
        assert shop.found_total == 1 and shop.state == "ok"
    assert route.call_count == 2  # one for the test on adding, one for the run's query


@respx.mock
async def test_shop_that_starts_blocking_is_paused(alice, monkeypatch):
    from app.sources import galaxus

    async def nothing(self, q):
        return []

    monkeypatch.setattr(galaxus.GalaxusAdapter, "search", nothing)
    respx.get("https://www.fotoshop.ch/robots.txt").mock(return_value=httpx.Response(200, text=""))
    respx.get(url__startswith="https://www.fotoshop.ch/suche").mock(
        side_effect=[httpx.Response(200, text=SEARCH_PAGE), httpx.Response(403, text="denied")]
    )
    await alice.post("/api/shops", json={"address": "https://www.fotoshop.ch/suche?q=olympus"})
    s = (await alice.post("/api/searches", json={"title": "Leica M6"})).json()
    async with sessionmaker()() as db:
        await run_search(db, uuid.UUID(s["id"]))
        shop = (await db.scalars(select(CustomShop))).one()
        assert shop.state == "blocked" and shop.paused_until is not None
        assert await shops.adapters_for(db, shop.user_id) == []  # left alone from now on


@respx.mock
async def test_compressed_pages_are_decoded_once():
    import gzip

    respx.get("https://gz.ch/robots.txt").mock(
        return_value=httpx.Response(
            200,
            content=gzip.compress(b"User-agent: *\nDisallow: /*?q="),
            headers={"content-encoding": "gzip"},
        )
    )
    assert not await safe_http.robots_allows("https://gz.ch/s?q=x")
    assert not (await safe_http.robots_for("https://gz.ch/")).unreachable
