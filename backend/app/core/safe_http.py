"""Outbound HTTP for user- or listing-supplied URLs (link import, images).

Guards against SSRF: https only, every hop's resolved address must be public,
bounded redirects, size and time limits. Respects robots.txt for page fetches.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx


def user_agent() -> str:
    from app.core.config import get_settings

    contact = get_settings().bot_contact_url.strip()
    return (
        f"SchnaeppliBot/0.1 (+{contact}; self-hosted shopping assistant)"
        if contact
        else ("SchnaeppliBot/0.1 (self-hosted shopping assistant; user-initiated fetch)")
    )


MAX_REDIRECTS = 3


class UnsafeURL(Exception):
    pass


async def _assert_public(host: str) -> None:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise UnsafeURL("The host could not be resolved.") from e
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global or addr.is_multicast:
            raise UnsafeURL("The address is not a public internet address.")


def _check_scheme(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise UnsafeURL("Only https:// links are supported.")
    if parts.username or parts.password:
        raise UnsafeURL("Links with credentials are not allowed.")
    if parts.port not in (None, 443):
        raise UnsafeURL("Only the standard https port is allowed.")
    return parts.hostname


async def safe_get(
    url: str, *, max_bytes: int = 2_000_000, timeout: float = 15.0, accept: str = "*/*"
) -> httpx.Response:
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=timeout, headers={"User-Agent": user_agent(), "Accept": accept}
    ) as client:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            host = _check_scheme(current)
            await _assert_public(host)
            async with client.stream("GET", current) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                    current = urljoin(current, resp.headers["location"])
                    continue
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise UnsafeURL("The response is too large.")
                return httpx.Response(
                    resp.status_code, headers=resp.headers, content=bytes(body), request=resp.request
                )
        raise UnsafeURL("Too many redirects.")


_robots_cache: dict[str, RobotFileParser] = {}


async def robots_allows(url: str) -> bool:
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.hostname}"
    rp = _robots_cache.get(base)
    if rp is None:
        rp = RobotFileParser()
        try:
            resp = await safe_get(base + "/robots.txt", max_bytes=500_000, timeout=8)
            if resp.status_code >= 400:
                rp.parse([])  # no robots.txt = allowed
            else:
                rp.parse(resp.text.splitlines())
        except (UnsafeURL, httpx.HTTPError):
            rp.parse(["User-agent: *", "Disallow: /"])  # can't check: be conservative
        _robots_cache[base] = rp
    return rp.can_fetch("SchnaeppliBot", url)


IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


async def fetch_image(url: str, max_bytes: int = 4_000_000) -> tuple[bytes, str] | None:
    try:
        resp = await safe_get(url, max_bytes=max_bytes, timeout=10, accept="image/*")
    except (UnsafeURL, httpx.HTTPError):
        return None
    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if resp.status_code != 200 or ctype not in IMAGE_TYPES:
        return None
    return resp.content, ctype
