"""Galaxus (and Digitec, which shares its catalogue) through Galaxus' official MCP server.

Digitec Galaxus opened ``https://mcp.galaxus.ch`` in November 2026 as an interface for
AI assistants: no account, the same product database as the shop, one tool
(``search_products``). It is the sanctioned way for an agent like Schnäppli to search
the shop; the website itself blocks automated clients and Schnäppli never goes there.

Results are new retail products (prices incl. VAT, no stock or delivery times). Besides
being offers in their own right, they tell the scorer what the item costs new.
"""

from __future__ import annotations

import json
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

import httpx
import structlog

from app.core.config import get_settings
from app.core.safe_http import user_agent
from app.sources.base import RawListing, SearchQuery, SourceAdapter, SourceError, SourceStatus

log = structlog.get_logger()

ENDPOINT = "https://mcp.galaxus.ch"
PROTOCOL = "2025-06-18"
# Galaxus asks agents to identify themselves; analytics only.
AGENT_INFO = "Schnäppli, a self-hosted shopping agent (https://github.com/DuarteSantos8/schnaeppli)"


def _strip_tracking(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def _sse_json(text: str) -> dict:
    """The server answers with Server-Sent Events or plain JSON; return the JSON-RPC message."""
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise SourceError("Galaxus answered in an unexpected format.")


class GalaxusAdapter(SourceAdapter):
    id = "galaxus"
    name = "Galaxus & Digitec"
    kind = "retail"
    region = "CH"
    homepage = "https://www.galaxus.ch"

    def __init__(self) -> None:
        self._session: str | None = None

    def status(self) -> SourceStatus:
        if not get_settings().galaxus_enabled:
            return SourceStatus(
                "unsupported", "Turned off by the administrator (SCHNAEPPLI_GALAXUS_ENABLED=false)."
            )
        return SourceStatus(
            "ready",
            "Official Galaxus interface for AI assistants. New products with current prices; "
            "Digitec shares the catalogue. Also used as the new-price reference for used listings.",
            docs="https://www.galaxus.ch/en/page/galaxus-introduces-mcp-interface-for-ai-assistants-44216",
        )

    def _headers(self) -> dict:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL,
        }
        if self._session:
            h["Mcp-Session-Id"] = self._session
        return h

    async def _rpc(self, client: httpx.AsyncClient, payload: dict) -> dict | None:
        r = await client.post(ENDPOINT, headers=self._headers(), json=payload)
        if r.status_code in (400, 404) and self._session and payload.get("method") != "initialize":
            raise _Expired()
        if r.status_code == 429:
            raise SourceError("Galaxus asked us to slow down; trying again next run.")
        if r.status_code >= 400:
            raise SourceError(f"Galaxus interface error {r.status_code}.")
        if "id" not in payload:  # notification
            return None
        return _sse_json(r.text)

    async def _connect(self, client: httpx.AsyncClient) -> None:
        self._session = None
        r = await client.post(
            ENDPOINT,
            headers=self._headers(),
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "schnaeppli", "version": "0.1"},
                },
            },
        )
        if r.status_code >= 400:
            raise SourceError(f"Couldn't connect to the Galaxus interface ({r.status_code}).")
        self._session = r.headers.get("mcp-session-id")
        await self._rpc(client, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def _call(self, client: httpx.AsyncClient, args: dict) -> dict:
        msg = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "search_products", "arguments": args},
        }
        for attempt in range(2):
            if not self._session:
                await self._connect(client)
            try:
                out = await self._rpc(client, msg)
                break
            except _Expired:
                self._session = None
                if attempt:
                    raise SourceError("The Galaxus session kept expiring.") from None
        assert out is not None
        if "error" in out:
            raise SourceError(f"Galaxus: {out['error'].get('message', 'error')}"[:200], retryable=False)
        result = out.get("result") or {}
        if result.get("isError"):
            text = " ".join(c.get("text", "") for c in result.get("content", []))
            raise SourceError(f"Galaxus: {text[:180]}", retryable=False)
        text = next((c["text"] for c in result.get("content", []) if c.get("type") == "text"), "")
        try:
            return json.loads(text) if text else (result.get("structuredContent") or {})
        except ValueError:
            raise SourceError("Galaxus returned data that couldn't be read.") from None

    async def search(self, query: SearchQuery) -> list[RawListing]:
        if query.condition == "used":
            return []  # new retail only; a used-only search has nothing to find here
        args: dict = {
            "query": query.text[:200],
            "agentInfo": AGENT_INFO,
            "language": "de",
            "first": min(max(query.limit, 1), 50),
        }
        if query.max_price:
            args["maxPrice"] = max(1, int(query.max_price))
            # Searching "camera" also returns screen protectors and batteries; a floor at a
            # fifth of the budget keeps accessories out of a search for the main item.
            args["minPrice"] = max(1, int(query.max_price * 0.2))
        async with httpx.AsyncClient(timeout=25, headers={"User-Agent": user_agent()}) as client:
            try:
                data = await self._call(client, args)
            except httpx.HTTPError as e:
                raise SourceError(f"Galaxus is unreachable: {type(e).__name__}") from e
        if data.get("errorMessage") and not data.get("products"):
            return []
        return [x for x in (self._parse(p) for p in data.get("products") or []) if x]

    def _parse(self, p: dict) -> RawListing | None:
        price = (p.get("priceIfAvailable") or {}).get("amountInclusive")
        url = p.get("pageUrl")
        if price is None or not url or not p.get("id"):
            return None
        name = p.get("name") or ""
        brand = p.get("brand") or ""
        title = name if not brand or name.lower().startswith(brand.lower()) else f"{brand} {name}"
        img = (p.get("previewImage") or {}).get("url")
        rating = p.get("ratingSummaryIfAvailable") or {}
        desc = (p.get("description") or "").strip()
        if rating.get("averageRating"):
            desc = (
                f"Rating {rating['averageRating']}/5 from {rating.get('ratingCount', 0)} reviews.\n\n{desc}"
            )
        return RawListing(
            source=self.id,
            external_id=str(p["id"]),
            url=_strip_tracking(url),
            title=title[:300],
            description=desc[:4000] or None,
            price=Decimal(str(price)),
            currency=(p.get("priceIfAvailable") or {}).get("currency") or "CHF",
            price_type="fixed",
            shipping_known=False,
            shipping_possible=True,
            pickup_possible=False,
            condition="new",
            condition_text="New (retail)",
            country="CH",
            seller={"name": "Galaxus", "type": "retailer"},
            images=[_strip_tracking(img)] if img else [],
            is_new_retail=True,
        )


class _Expired(Exception):
    pass
