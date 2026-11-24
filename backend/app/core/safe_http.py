"""Outbound HTTP for user- or listing-supplied URLs (link import, images).

Guards against SSRF: https only, every hop's resolved address must be public,
bounded redirects, size and time limits. Respects robots.txt for page fetches.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

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
                # aiter_bytes() already decoded gzip/br: drop the encoding headers so the
                # copy isn't decoded a second time.
                headers = [
                    (k, v)
                    for k, v in resp.headers.multi_items()
                    if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
                ]
                return httpx.Response(
                    resp.status_code, headers=headers, content=bytes(body), request=resp.request
                )
        raise UnsafeURL("Too many redirects.")


class Robots:
    """robots.txt as RFC 9309 reads it: the group for our token (else ``*``), ``*`` and
    ``$`` in paths, the longest matching rule wins and Allow wins a tie. (The standard
    library's parser ignores wildcards, which would let Schnäppli fetch pages a site
    closed with patterns like ``Disallow: /*?q=``.)"""

    AGENT = "schnaepplibot"

    def __init__(
        self, text: str = "", *, allow_all: bool = False, deny_all: bool = False, unreachable: bool = False
    ):
        self.unreachable = unreachable
        self.rules: list[tuple[bool, str]] = []
        if deny_all:
            self.rules = [(False, "/")]
        elif not allow_all:
            self.rules = self._parse(text)

    @classmethod
    def _parse(cls, text: str) -> list[tuple[bool, str]]:
        groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if not last_was_agent:
                    agents, rules = [], []
                    groups.append((agents, rules))
                agents.append(val.lower())
                last_was_agent = True
            elif key in ("allow", "disallow"):
                last_was_agent = False
                if groups and (val or key == "allow"):
                    rules.append((key == "allow", val))
            else:
                last_was_agent = False
        mine = [r for a, rs in groups for r in rs if any(cls.AGENT.startswith(x) and x != "*" for x in a)]
        if mine:
            return mine
        return [r for a, rs in groups for r in rs if "*" in a]

    @staticmethod
    def _match(pattern: str, path: str) -> bool:
        anchored = pattern.endswith("$")
        rx = re.escape(pattern.rstrip("$")).replace(r"\*", ".*")
        return re.match(rx + ("$" if anchored else ""), path) is not None

    def allows(self, url: str) -> bool:
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        best: tuple[int, bool] | None = None
        for allow, pattern in self.rules:
            if pattern and self._match(pattern, path):
                key = (len(pattern), allow)
                if best is None or key > best:
                    best = key
        return True if best is None else best[1]


_robots_cache: dict[str, tuple[float, Robots]] = {}
ROBOTS_TTL = 6 * 3600


async def robots_for(url: str) -> Robots:
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.hostname}"
    cached = _robots_cache.get(base)
    if cached is None or time.monotonic() - cached[0] > ROBOTS_TTL:
        try:
            resp = await safe_get(base + "/robots.txt", max_bytes=500_000, timeout=8)
            if resp.status_code >= 500:
                rp = Robots(deny_all=True, unreachable=True)  # assume closed (RFC 9309)
            elif resp.status_code >= 400:
                rp = Robots(allow_all=True)  # no robots.txt = allowed
            else:
                rp = Robots(resp.text)
        except (UnsafeURL, httpx.HTTPError):
            rp = Robots(deny_all=True, unreachable=True)  # can't check: be conservative
        cached = (time.monotonic(), rp)
        _robots_cache[base] = cached
    return cached[1]


async def robots_allows(url: str) -> bool:
    return (await robots_for(url)).allows(url)


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
