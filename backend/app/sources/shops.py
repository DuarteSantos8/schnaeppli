"""Shops a user adds themselves, searched with every search.

Schnäppli only reads what a shop publishes for machines, and only where it may:

* **WooCommerce shops**: the public Store API (``/wp-json/wc/store/v1/products``),
  which WooCommerce offers for exactly this.
* **Any other shop**: its search page, if robots.txt allows it, read through the
  schema.org product data shops add for search engines (JSON-LD or microdata).

A shop that refuses automated visitors (403/429, a captcha or "are you human" page)
is marked *blocked* and left alone for a week; Schnäppli never tries to get around
that. One request per shop and search term, at most one every few seconds per host,
and results are cached for half an hour.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
import time
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from app.core.db import utcnow
from app.core.safe_http import UnsafeURL, robots_for, safe_get
from app.sources.base import RawListing, SearchQuery, SourceAdapter, SourceError, SourceStatus
from app.sources.link import _JSONLD, _dec

QUERY = "{query}"
SEARCH_PARAMS = (
    "q", "query", "search", "s", "k", "keyword", "keywords", "term", "searchterm", "search_query",
    "searchquery", "suche", "text", "w", "qs", "sw", "sword", "ssearch", "search_text", "find",
)  # fmt: skip
BLOCK_MARKERS = (
    "captcha", "are you a human", "are you human", "kurze prüfung", "just a moment",
    "cf-chl", "challenge-platform", "access denied", "px-captcha", "datadome", "verify you are",
    "bot protection", "unusual traffic",
)  # fmt: skip
BLOCK_PAUSE = timedelta(days=7)
CACHE_TTL = 30 * 60
HOST_GAP = 4.0
MAX_ITEMS = 30

# Sites that are built in, or that turn automated clients away on principle.
HANDLED = {
    "ebay.ch": "eBay is built in (Settings → Sources).",
    "ebay.de": "eBay is built in (Settings → Sources).",
    "ebay.com": "eBay is built in (Settings → Sources).",
    "galaxus.ch": "Galaxus is built in and searched with every search.",
    "digitec.ch": "Digitec is built in (through Galaxus) and searched with every search.",
    "ricardo.ch": "Ricardo works through its alert e-mails (Settings → Sources).",
    "tutti.ch": "tutti works through its alert e-mails (Settings → Sources).",
    "amazon.de": "Amazon forbids automated access in its terms and blocks AI agents in robots.txt.",
    "amazon.com": "Amazon forbids automated access in its terms and blocks AI agents in robots.txt.",
    "amazon.fr": "Amazon forbids automated access in its terms and blocks AI agents in robots.txt.",
    "amazon.it": "Amazon forbids automated access in its terms and blocks AI agents in robots.txt.",
    "facebook.com": "Meta's terms prohibit automated collection from Marketplace.",
}

STATE_TEXT = {
    "ok": "Working",
    "robots": "The shop's robots.txt closes its search to programs.",
    "blocked": "The shop turns automated visitors away (bot check or 403).",
    "no_data": "The search page has no machine-readable product data Schnäppli could read.",
    "error": "The shop couldn't be reached.",
    "untested": "Not tested yet.",
}


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def handled_reason(host: str) -> str | None:
    for h, why in HANDLED.items():
        if host == h or host.endswith("." + h):
            return why
    return None


class ShopBlocked(SourceError):
    def __init__(self, state: str, message: str):
        super().__init__(message, retryable=False)
        self.state = state


# --------------------------------------------------------------------- templates
@dataclass
class Template:
    mode: str  # "woo" | "page"
    url: str  # contains {query}
    example: str | None = None  # the term found in a pasted search URL


def template_from(address: str) -> Template:
    """Turn what the user pasted (a shop's address or one of its search pages) into a
    search template. Raises ValueError with a message for the user."""
    address = address.strip()
    if not address.startswith(("http://", "https://")):
        address = "https://" + address
    parts = urlsplit(address)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("Use the shop's https:// address.")
    if QUERY in address:
        return Template("page", address)
    params = parse_qsl(parts.query, keep_blank_values=True)
    for i, (k, v) in enumerate(params):
        if k.lower() in SEARCH_PARAMS and v.strip():
            params[i] = (k, "__Q__")
            query = urlencode(params).replace("__Q__", QUERY)
            return Template("page", urlunsplit(parts._replace(query=query, fragment="")), example=v)
    if parts.path.strip("/") == "" and not parts.query:
        root = f"https://{parts.hostname}"
        return Template("woo", root + "/wp-json/wc/store/v1/products?search=" + QUERY + "&per_page=30")
    raise ValueError(
        "Schnäppli couldn't tell where the search word goes in this address. Search for something on "
        "the shop, copy the address of the results page and paste it, or put {query} where the word is."
    )


def fill(template: str, text: str) -> str:
    q = quote(text) if "?" not in template.split(QUERY)[0] else quote_plus(text)
    return template.replace(QUERY, q, 1)


# ---------------------------------------------------------------------- parsing
def _walk(node):
    if isinstance(node, list):
        for n in node:
            yield from _walk(n)
    elif isinstance(node, dict):
        yield node
        for k in ("@graph", "itemListElement", "mainEntity", "item", "hasVariant"):
            if k in node:
                yield from _walk(node[k])


def _types(node: dict) -> list[str]:
    t = node.get("@type")
    return [str(x) for x in (t if isinstance(t, list) else [t])]


def _offer_price(offers) -> tuple[Decimal | None, str | None, str | None]:
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if not isinstance(offers, dict):
        return None, None, None
    price = offers.get("lowPrice") if "AggregateOffer" in _types(offers) else offers.get("price")
    if price is None and isinstance(offers.get("priceSpecification"), dict):
        price = offers["priceSpecification"].get("price")
    return _dec(price), offers.get("priceCurrency"), str(offers.get("itemCondition") or "")


def _image(v) -> str | None:
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, dict):
        v = v.get("url") or v.get("contentUrl")
    return v if isinstance(v, str) else None


@dataclass
class Item:
    title: str
    url: str
    price: Decimal | None
    currency: str | None
    image: str | None
    condition: str | None
    description: str | None = None


def items_from_jsonld(page: str, base: str) -> list[Item]:
    out = []
    for block in _JSONLD.findall(page):
        try:
            data = json.loads(html.unescape(block.strip()))
        except ValueError:
            continue
        for node in _walk(data):
            if "Product" not in _types(node) and "ProductGroup" not in _types(node):
                continue
            price, cur, cond = _offer_price(node.get("offers"))
            offers = node.get("offers")
            url = node.get("url") or (offers.get("url") if isinstance(offers, dict) else None)
            if not node.get("name") or not url:
                continue
            out.append(
                Item(str(node["name"]), urljoin(base, str(url)), price, cur, _image(node.get("image")), cond,
                     str(node.get("description") or "")[:2000] or None)
            )  # fmt: skip
    return out


class _Microdata(HTMLParser):
    """schema.org/Product in microdata: itemscope/itemprop attributes."""

    VOID = {"img", "meta", "link", "br", "hr", "input", "source", "wbr"}

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.stack: list[tuple[str, bool]] = []  # (tag, opened a scope)
        self.scopes: list[dict] = []
        self.items: list[dict] = []
        self.texts: list[tuple[int, dict, str, list[str]]] = []  # (depth, scope, prop, buffer)

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        prop = a.get("itemprop", "").strip()
        opened = False
        if "itemscope" in a:
            scope = {"_type": a.get("itemtype", "")}
            if prop and self.scopes:
                self.scopes[-1].setdefault(prop, scope)
            if "schema.org/Product" in scope["_type"]:
                self.items.append(scope)
            if tag not in self.VOID:
                self.scopes.append(scope)
                opened = True
        elif prop and self.scopes:
            val = a.get("content") or a.get("href") or a.get("src") or a.get("data-src")
            if val:
                if prop in ("url", "image"):
                    val = urljoin(self.base, val)
                self.scopes[-1].setdefault(prop, val)
            elif tag not in self.VOID:
                self.texts.append((len(self.stack), self.scopes[-1], prop, []))
        if tag not in self.VOID:
            self.stack.append((tag, opened))

    def handle_data(self, data):
        for *_, buf in self.texts:
            buf.append(data)

    def handle_endtag(self, tag):
        if not any(t == tag for t, _ in self.stack):
            return
        while self.stack:
            t, opened = self.stack.pop()
            depth = len(self.stack)
            while self.texts and self.texts[-1][0] >= depth:
                _, scope, prop, buf = self.texts.pop()
                scope.setdefault(prop, " ".join("".join(buf).split()))
            if opened and self.scopes:
                self.scopes.pop()
            if t == tag:
                break


def items_from_microdata(page: str, base: str) -> list[Item]:
    p = _Microdata(base)
    try:
        p.feed(page)
    except Exception:  # noqa: BLE001, S110 - broken markup: use what was read
        pass
    out = []
    for d in p.items:
        offer = d.get("offers") if isinstance(d.get("offers"), dict) else {}
        price = _dec(re.sub(r"[^\d.,']", "", str(offer.get("price") or d.get("price") or "")) or None)
        url = offer.get("url") or d.get("url")
        if d.get("name") and isinstance(url, str):
            out.append(
                Item(str(d["name"]), url, price, offer.get("priceCurrency"), d.get("image") if isinstance(d.get("image"), str) else None,
                     str(offer.get("itemCondition") or ""), None)
            )  # fmt: skip
    return out


def items_from_woo(data, base: str) -> list[Item]:
    out = []
    for p in data if isinstance(data, list) else []:
        if not isinstance(p, dict) or not p.get("permalink"):
            continue
        prices = p.get("prices") or {}
        minor = int(prices.get("currency_minor_unit") or 0)
        raw = prices.get("price")
        price = (Decimal(str(raw)) / (10**minor)) if raw not in (None, "") and str(raw).isdigit() else None
        imgs = p.get("images") or []
        desc = re.sub(r"<[^>]+>", " ", html.unescape(p.get("short_description") or "")).strip()
        out.append(
            Item(html.unescape(str(p.get("name") or "")), str(p["permalink"]), price, prices.get("currency_code"),
                 imgs[0].get("src") if imgs and isinstance(imgs[0], dict) else None, "new", desc[:2000] or None)
        )  # fmt: skip
    return out


def _looks_blocked(resp: httpx.Response) -> bool:
    if resp.status_code in (401, 403, 429, 503):
        return True
    head = resp.text[:20_000].lower() if len(resp.content) < 200_000 else ""
    return any(m in head for m in BLOCK_MARKERS)


_TOKEN = re.compile(r"[a-z0-9äöüéèà]+")


def relevant(title: str, query: str) -> bool:
    words = [w for w in _TOKEN.findall(query.lower()) if len(w) > 1]
    if not words:
        return True
    t = title.lower()
    return sum(w in t for w in words) >= max(1, (len(words) + 1) // 2)


# ---------------------------------------------------------------------- fetching
_host_locks: dict[str, asyncio.Lock] = {}
_host_last: dict[str, float] = {}
_cache: dict[tuple[str, str], tuple[float, list[Item]]] = {}


async def _polite_get(url: str, accept: str) -> httpx.Response:
    host = host_of(url)
    lock = _host_locks.setdefault(host, asyncio.Lock())
    async with lock:
        wait = HOST_GAP - (time.monotonic() - _host_last.get(host, 0))
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await safe_get(url, max_bytes=4_000_000, timeout=20, accept=accept)
        finally:
            _host_last[host] = time.monotonic()


async def fetch_items(mode: str, template: str, text: str) -> list[Item]:
    """One search on one shop. Raises ShopBlocked for robots/blocked/no data."""
    key = (template, text.lower())
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    url = fill(template, text)
    robots = await robots_for(url)
    if robots.unreachable:
        raise SourceError(STATE_TEXT["error"])
    if not robots.allows(url):
        raise ShopBlocked("robots", STATE_TEXT["robots"])
    accept = "application/json" if mode == "woo" else "text/html,application/xhtml+xml"
    try:
        resp = await _polite_get(url, accept)
    except UnsafeURL as e:
        raise SourceError(str(e), retryable=False) from e
    except httpx.HTTPError as e:
        raise SourceError(STATE_TEXT["error"]) from e
    if _looks_blocked(resp):
        raise ShopBlocked("blocked", STATE_TEXT["blocked"])
    if resp.status_code == 404 and mode == "woo":
        raise ShopBlocked(
            "no_data", "This isn't a WooCommerce shop. Paste the address of a search results page instead."
        )
    if resp.status_code >= 400:
        raise SourceError(f"The shop answered {resp.status_code}.")
    if mode == "woo":
        try:
            items = items_from_woo(resp.json(), url)
        except ValueError as e:
            raise ShopBlocked(
                "no_data",
                "This isn't a WooCommerce shop. Paste the address of a search results page instead.",
            ) from e
    else:
        page = resp.text
        items = items_from_jsonld(page, url) or items_from_microdata(page, url)
        if not items and not _empty_results(page):
            raise ShopBlocked("no_data", STATE_TEXT["no_data"])
    seen, out = set(), []
    for it in items:
        if it.url not in seen and it.title:
            seen.add(it.url)
            out.append(it)
    out = out[:MAX_ITEMS]
    _cache[key] = (time.monotonic(), out)
    return out


def _empty_results(page: str) -> bool:
    """A page with product markup elsewhere but no hits this time is fine; a page with
    no product markup at all can't be read."""
    low = page.lower()
    return "schema.org/product" in low or '"@type":"product"' in low.replace(" ", "")


# ---------------------------------------------------------------------- adapter
class ShopAdapter(SourceAdapter):
    """One user-added shop. ``outcome`` is read by the runner afterwards to update the
    shop's state."""

    def __init__(self, shop):
        self.shop_id = shop.id
        self.id = shop.host[:30]
        self.name = shop.name
        self.kind = shop.kind or "retail"
        self.homepage = f"https://{shop.host}"
        self.mode, self.template = shop.mode, shop.search_url
        self.outcome: tuple[str, str | None] | None = None
        self.found = 0

    def status(self) -> SourceStatus:
        return SourceStatus("ready", "Added by you.")

    async def search(self, query: SearchQuery) -> list[RawListing]:
        if query.condition == "used" and self.kind == "retail":
            return []
        try:
            items = await fetch_items(self.mode, self.template, query.text)
        except ShopBlocked as e:
            self.outcome = (e.state, str(e))
            raise
        except SourceError as e:
            self.outcome = ("error", str(e))
            raise
        out = []
        for it in items:
            if not relevant(it.title, query.text):
                continue
            if query.max_price and it.price is not None and float(it.price) > query.max_price:
                continue
            out.append(to_raw(self.id, self.kind, it))
        self.found += len(out)
        self.outcome = ("ok", None)
        return out


def to_raw(source: str, kind: str, it: Item) -> RawListing:
    cond = (it.condition or "").lower()
    condition = (
        "used"
        if "used" in cond
        else "refurbished"
        if "refurb" in cond
        else "new"
        if kind == "retail" or "new" in cond
        else None
    )
    url = it.url.split("#")[0]
    return RawListing(
        source=source,
        external_id=hashlib.sha256(url.encode()).hexdigest()[:32],
        url=url,
        title=it.title[:500],
        description=it.description,
        price=it.price,
        currency=(it.currency or "CHF")[:3].upper(),
        condition=condition,
        images=[it.image] if it.image and it.image.startswith("https://") else [],
        is_new_retail=kind == "retail" and condition == "new",
    )


async def record(db, adapters) -> None:
    """Store what the run learned about each shop."""
    from app.models import CustomShop

    now = utcnow()
    for a in adapters:
        if not isinstance(a, ShopAdapter) or a.outcome is None:
            continue
        shop = await db.get(CustomShop, a.shop_id)
        if shop is None:
            continue
        state, detail = a.outcome
        shop.state, shop.state_detail, shop.checked_at = state, detail, now
        if state in ("blocked", "robots", "no_data"):
            shop.paused_until = now + BLOCK_PAUSE
        else:
            shop.paused_until = None
            shop.found_total = (shop.found_total or 0) + a.found


async def adapters_for(db, user_id) -> list[ShopAdapter]:
    """The user's shops a search run asks: enabled, working or untested, not paused."""
    from sqlalchemy import select

    from app.models import CustomShop

    now = utcnow()
    rows = (
        await db.scalars(
            select(CustomShop).where(CustomShop.user_id == user_id, CustomShop.enabled.is_(True))
        )
    ).all()
    return [
        ShopAdapter(s)
        for s in rows
        if s.state in ("ok", "untested", "error") and not (s.paused_until and s.paused_until > now)
    ]
