import json

import httpx
import respx

from app.sources.base import SearchQuery
from app.sources.galaxus import ENDPOINT, GalaxusAdapter

PRODUCTS = {
    "correctedSearchTerm": None,
    "totalCount": 2,
    "products": [
        {
            "id": 42944935,
            "name": "X100VI",
            "brand": "Fujifilm",
            "description": "Kompaktkamera",
            "priceIfAvailable": {"amountInclusive": 1698, "currency": "CHF"},
            "pageUrl": "https://www.galaxus.ch/de/s1/product/fujifilm-x100vi-42944935?utm_source=shop-mcp",
            "previewImage": {
                "url": "https://www.galaxus.ch/productimages/1/2/3?utm_source=shop-mcp",
                "width": 736,
            },
            "ratingSummaryIfAvailable": {"averageRating": 4.4, "ratingCount": 48},
        },
        {
            "id": 7,
            "name": "No price",
            "brand": "X",
            "priceIfAvailable": None,
            "pageUrl": "https://www.galaxus.ch/x",
        },
    ],
}


def _sse(obj: dict) -> str:
    return "event: message\ndata: " + json.dumps(obj) + "\n\n"


@respx.mock
async def test_search_maps_products_and_sends_mcp_handshake():
    calls = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        calls.append((body.get("method"), request.headers.get("mcp-session-id")))
        if body["method"] == "initialize":
            return httpx.Response(
                200, headers={"mcp-session-id": "s1"}, text=_sse({"jsonrpc": "2.0", "id": 1, "result": {}})
            )
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        args = body["params"]["arguments"]
        assert args["maxPrice"] == 2000 and args["minPrice"] == 400  # accessories filtered by the floor
        assert "Schnäppli" in args["agentInfo"]
        result = {"content": [{"type": "text", "text": json.dumps(PRODUCTS)}]}
        return httpx.Response(200, text=_sse({"jsonrpc": "2.0", "id": 2, "result": result}))

    respx.post(ENDPOINT).mock(side_effect=handler)
    items = await GalaxusAdapter().search(SearchQuery(text="Fujifilm X100", max_price=2000))
    assert [m for m, _ in calls] == ["initialize", "notifications/initialized", "tools/call"]
    assert calls[-1][1] == "s1"  # the session id is sent back
    assert len(items) == 1  # products without a price are skipped
    it = items[0]
    assert it.title == "Fujifilm X100VI" and str(it.price) == "1698"
    assert it.url == "https://www.galaxus.ch/de/s1/product/fujifilm-x100vi-42944935"  # tracking removed
    assert it.images == ["https://www.galaxus.ch/productimages/1/2/3"]
    assert it.is_new_retail and it.condition == "new"
    assert it.description.startswith("Rating 4.4/5")


async def test_used_only_search_skips_galaxus():
    assert await GalaxusAdapter().search(SearchQuery(text="x", condition="used")) == []


@respx.mock
async def test_expired_session_reconnects():
    state = {"inits": 0, "calls": 0}

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        if body["method"] == "initialize":
            state["inits"] += 1
            return httpx.Response(200, headers={"mcp-session-id": f"s{state['inits']}"}, text="{}")
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        state["calls"] += 1
        if request.headers.get("mcp-session-id") == "s1":
            return httpx.Response(404)
        result = {"content": [{"type": "text", "text": json.dumps({"products": []})}]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": result})

    respx.post(ENDPOINT).mock(side_effect=handler)
    adapter = GalaxusAdapter()
    assert await adapter.search(SearchQuery(text="x")) == []
    assert state["inits"] == 2
