"""Add a single listing by link (user-initiated).

Fetches exactly one page the user pasted, only if robots.txt allows it, and reads
the structured data the shop publishes for search engines (schema.org Product
JSON-LD, then OpenGraph). No crawling, no login, no anti-bot workarounds.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from app.core.safe_http import UnsafeURL, robots_allows, safe_get
from app.sources.base import RawListing, SourceError, SourceStatus

_JSONLD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
_META = re.compile(
    r'<meta\s+[^>]*(?:property|name)=["\']([^"\']+)["\'][^>]*content=["\']([^"\']*)["\']', re.I
)
_META_REV = re.compile(
    r'<meta\s+[^>]*content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']([^"\']+)["\']', re.I
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)

KNOWN = {
    "ricardo.ch": "ricardo",
    "tutti.ch": "tutti",
    "anibis.ch": "anibis",
    "digitec.ch": "digitec",
    "galaxus.ch": "galaxus",
    "interdiscount.ch": "interdiscount",
    "toppreise.ch": "toppreise",
    "amazon.de": "amazon",
    "amazon.com": "amazon",
    "ebay.ch": "ebay",
    "ebay.de": "ebay",
    "brack.ch": "brack",
}
RETAIL = {"digitec", "galaxus", "interdiscount", "amazon", "brack", "toppreise"}


def status() -> SourceStatus:
    return SourceStatus(
        "manual", "Paste a link to any listing. Schnäppli reads it once, only where robots.txt allows."
    )


def _dec(v) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v).replace("'", "").replace(",", ".").strip())
    except InvalidOperation:
        return None


def _walk(node):
    if isinstance(node, list):
        for n in node:
            yield from _walk(n)
    elif isinstance(node, dict):
        yield node
        for k in ("@graph", "itemListElement", "mainEntity"):
            if k in node:
                yield from _walk(node[k])


def _product_from_jsonld(page: str) -> dict | None:
    for block in _JSONLD.findall(page):
        try:
            data = json.loads(html.unescape(block.strip()))
        except ValueError:
            continue
        for node in _walk(data):
            t = node.get("@type")
            types = t if isinstance(t, list) else [t]
            if "Product" in types or "Offer" in types:
                return node
    return None


def parse_page(url: str, page: str) -> RawListing:
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    source = KNOWN.get(host, "web")
    meta = {k.lower(): html.unescape(v) for k, v in _META.findall(page)}
    meta |= {k.lower(): html.unescape(v) for v, k in _META_REV.findall(page) if k.lower() not in meta}
    product = _product_from_jsonld(page) or {}
    offers = product.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if isinstance(offers, dict) and offers.get("@type") == "AggregateOffer":
        price = offers.get("lowPrice")
    else:
        price = offers.get("price") if isinstance(offers, dict) else None
    price = price or meta.get("product:price:amount") or meta.get("og:price:amount")
    currency = (
        (offers.get("priceCurrency") if isinstance(offers, dict) else None)
        or meta.get("product:price:currency")
        or "CHF"
    )
    cond = str(offers.get("itemCondition", "") if isinstance(offers, dict) else "").lower()
    condition = (
        "new" if "new" in cond else "used" if "used" in cond else "refurbished" if "refurb" in cond else None
    )
    images = product.get("image") or meta.get("og:image") or []
    if isinstance(images, str):
        images = [images]
    images = [i.get("url") if isinstance(i, dict) else i for i in images]
    title_m = _TITLE.search(page)
    title = (
        product.get("name")
        or meta.get("og:title")
        or (html.unescape(title_m.group(1).strip()) if title_m else url)
    )
    desc = product.get("description") or meta.get("og:description") or meta.get("description")
    return RawListing(
        source=source,
        external_id=hashlib.sha256(url.split("#")[0].encode()).hexdigest()[:32],
        url=url,
        title=str(title)[:500],
        description=str(desc)[:8000] if desc else None,
        price=_dec(price),
        currency=str(currency)[:3].upper(),
        condition=condition or ("new" if source in RETAIL else None),
        images=[i for i in images if isinstance(i, str) and i.startswith("https://")][:8],
        is_new_retail=source in RETAIL,
    )


async def import_link(url: str) -> RawListing:
    try:
        if not await robots_allows(url):
            raise SourceError(
                "This site's robots.txt does not allow automated access to this page, so Schnäppli won't fetch it. "
                "You can still add the listing manually.",
                retryable=False,
            )
        resp = await safe_get(url, accept="text/html,application/xhtml+xml")
    except UnsafeURL as e:
        raise SourceError(str(e), retryable=False) from e
    if resp.status_code in (401, 403, 429) or "cf-mitigated" in resp.headers:
        raise SourceError(
            "The site refused automated access. Schnäppli does not work around bot protection; add the listing "
            "manually instead.",
            retryable=False,
        )
    if resp.status_code >= 400:
        raise SourceError(f"The page returned HTTP {resp.status_code}.", retryable=False)
    if "html" not in resp.headers.get("content-type", ""):
        raise SourceError("The link does not point to a web page.", retryable=False)
    return parse_page(url, resp.text)
