"""Ricardo and tutti.ch through their own saved-search alert e-mails.

Neither site offers a search API, and both turn automated clients away. What both do
offer is a saved search ("Suchabo" / "Suchauftrag") that e-mails new listings. The
user forwards those mails to a mailbox that belongs to Schnäppli; this module reads
that mailbox over IMAP, takes the listings out of the mails and hands them to the
normal pipeline (dedupe, free pre-filter, AI analysis, Deal Score, alerts).

Only the mail is used: Schnäppli doesn't open the listing pages on those sites. The
analysis therefore works from the title, price and photo in the alert.

Mail parsing is deliberately generic (listing links, the text and image around them,
a CHF amount nearby), because the alert layouts change without notice. A mail with
alert links that yields nothing is counted, so a layout change shows up in the status.
"""

from __future__ import annotations

import asyncio
import contextlib
import email
import email.policy
import imaplib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

import structlog

from app.core.config import get_settings
from app.sources.base import RawListing

log = structlog.get_logger()

SITES = {
    "ricardo": re.compile(r"^https?://(?:www\.)?ricardo\.ch/(?:de|fr|it|en)/a/[^?#\s]*?(\d{6,})/?$", re.I),
    "tutti": re.compile(r"^https?://(?:www\.)?tutti\.ch/(?:de|fr|it)/vi/[^?#\s]*?(\d{5,})/?$", re.I),
    "facebook": re.compile(r"^https?://(?:www\.|m\.|web\.)?facebook\.com/marketplace/item/(\d{6,})/?$", re.I),
    "toppreise": re.compile(r"^https?://(?:www\.)?toppreise\.ch/preisvergleich/[^?#\s]+-p(\d{3,})/?$", re.I),
}
# Price-alert mails describe new products in shops, not second-hand listings.
RETAIL_SITES = {"toppreise"}
PRICE = re.compile(
    r"(?:CHF|Fr\.|SFr\.?)\s*([0-9][0-9'’\s]*(?:[.,][0-9]{2})?)|([0-9][0-9'’]*(?:[.,][0-9]{2})?)\s*(?:CHF|Fr\.)|([0-9][0-9'’]*)\.[–-]",
    re.I,
)


def _canonical(url: str) -> tuple[str, str, str] | None:
    """(site, external id, clean URL) for a listing link, following tracking redirects."""
    for candidate in _unwrap(unescape(url.strip())):
        p = urlsplit(candidate)
        clean = urlunsplit((p.scheme or "https", p.netloc.lower(), p.path, "", ""))
        for site, rx in SITES.items():
            m = rx.match(clean)
            if m:
                return site, m.group(1), clean
    return None


def _unwrap(url: str, depth: int = 0) -> list[str]:
    """The URL itself plus any URL hidden in its query string (click-tracking redirects)."""
    out = [url]
    if depth > 2:
        return out
    p = urlsplit(url)
    if p.netloc.lower().endswith("facebook.com") and p.path.rstrip("/") == "/n" and p.query:
        # Facebook mail links: /n/?marketplace%2Fitem%2F123%2F&aref=… (the target path is the first key)
        out.append(f"https://www.facebook.com/{unquote(p.query.split('&', 1)[0]).lstrip('/')}")
    for _k, v in parse_qsl(urlsplit(url).query, keep_blank_values=False):
        v = unquote(v)
        if v.startswith("http"):
            out += _unwrap(v, depth + 1)
    return out


def _price(text: str) -> Decimal | None:
    m = PRICE.search(text)
    if not m:
        return None
    raw = next(g for g in m.groups() if g)
    raw = raw.replace("'", "").replace("’", "").replace(" ", "").replace(",", ".")
    try:
        v = Decimal(raw)
    except InvalidOperation:
        return None
    return v if 0 < v < 1_000_000 else None


@dataclass
class _Item:
    site: str
    ext_id: str
    url: str
    texts: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)


class _AlertParser(HTMLParser):
    """Walks the mail HTML once, attributing text and images to the listing link they belong to."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: dict[tuple[str, str], _Item] = {}
        self.current: _Item | None = None  # inside a listing link
        self.last: _Item | None = None  # most recent listing (text after it may hold the price)
        self.skip = 0  # inside <style>/<script>

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("style", "script", "head"):
            self.skip += 1
        elif tag == "a" and a.get("href"):
            hit = _canonical(a["href"])
            if hit:
                key = (hit[0], hit[1])
                self.current = self.items.setdefault(key, _Item(*hit))
                self.last = self.current
        elif tag == "img" and (src := a.get("src")) and src.startswith("https://"):
            target = self.current or self.last
            if (
                target
                and len(target.images) < 3
                and not re.search(r"logo|icon|pixel|spacer|tracking", src, re.I)
            ):
                w = a.get("width")
                if not (w and w.isdigit() and int(w) < 40):
                    target.images.append(src)

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag == "a":
            self.current = None

    def handle_data(self, data):
        if self.skip:
            return
        t = " ".join(data.split())
        if not t:
            return
        if self.current:
            self.current.texts.append(t)
        elif self.last and len(" ".join(self.last.after)) < 400:
            self.last.after.append(t)


@dataclass
class ParsedAlert:
    site: str | None
    search_name: str
    listings: list[RawListing]
    had_links: bool


def _plain_items(text: str) -> list[_Item]:
    """Plain-text alerts list each listing as a few lines followed by its link."""
    items: dict[tuple[str, str], _Item] = {}
    block: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        for url in re.findall(r"https?://\S+", line):
            hit = _canonical(url.rstrip(").,>"))
            if hit:
                it = items.setdefault((hit[0], hit[1]), _Item(*hit))
                it.texts += [t for t in block if not re.search(r"https?://", t)][-3:]
                block = []
        if line and not re.match(r"https?://", line):
            block.append(line)
        elif not line:
            block = []
    for it in items.values():  # the title is the first line, the price may be on any of them
        it.after = it.texts[1:]
        it.texts = it.texts[:1]
    return list(items.values())


def _search_name(subject: str) -> str:
    """'Neue Angebote für «Sony RX100»' → 'Sony RX100' (falls back to the whole subject)."""
    m = re.search(r"[«\"“„']([^»\"”“']{2,80})[»\"”“']", subject)
    return (m.group(1) if m else subject).strip()[:120]


def parse_alert(raw: bytes) -> ParsedAlert:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    subject = str(msg.get("Subject", ""))
    html_part = msg.get_body(preferencelist=("html",))
    if html_part is not None:
        p = _AlertParser()
        p.feed(html_part.get_content())
        found = list(p.items.values())
    else:
        plain = msg.get_body(preferencelist=("plain",))
        found = _plain_items(plain.get_content()) if plain is not None else []
    out: list[RawListing] = []
    for it in found:
        texts = [
            t
            for t in it.texts
            if not re.fullmatch(r"(?i)(ansehen|anzeigen|mehr|details|view|voir|vedi|jetzt bieten|kaufen)", t)
        ]
        title = max(texts, key=len, default="")
        if not title or title.startswith("http"):
            title = (
                re.sub(r"[-_]+", " ", urlsplit(it.url).path.rstrip("/").split("/")[-1])
                .rsplit(" ", 1)[0]
                .strip()
            )
        price = _price(" ".join(it.texts + it.after))
        out.append(
            RawListing(
                source=it.site,
                external_id=it.ext_id,
                url=it.url,
                title=title[:300] or f"{it.site} listing {it.ext_id}",
                description=None,
                price=price,
                currency="CHF",
                price_type="fixed",
                shipping_known=False,
                condition="new" if it.site in RETAIL_SITES else None,
                country="CH",
                seller={},
                images=it.images[:1],
                is_new_retail=it.site in RETAIL_SITES,
            )
        )
    site = out[0].source if out else None
    return ParsedAlert(site, _search_name(subject), out, had_links=bool(found))


# ----------------------------------------------------------------------- IMAP
@dataclass
class InboxBatch:
    alerts: list[ParsedAlert]
    unreadable: int
    checked_at: datetime


def configured() -> bool:
    s = get_settings()
    return bool(s.inbox_imap_host and s.inbox_imap_user and s.inbox_password)


def _fetch_sync(max_messages: int = 50) -> tuple[list[bytes], list[bytes]]:
    """Unread mails from the last 14 days. Returns (message bytes, IMAP ids). Marks nothing yet."""
    s = get_settings()
    box = imaplib.IMAP4_SSL(s.inbox_imap_host, s.inbox_imap_port, timeout=30)
    try:
        box.login(s.inbox_imap_user, s.inbox_password)
        box.select(s.inbox_imap_folder)
        since = (datetime.now() - timedelta(days=14)).strftime("%d-%b-%Y")
        typ, data = box.search(None, "UNSEEN", "SINCE", since)
        ids = (data[0] or b"").split()[:max_messages] if typ == "OK" else []
        mails = []
        for i in ids:
            typ, parts = box.fetch(i, "(BODY.PEEK[])")
            if typ == "OK" and parts and isinstance(parts[0], tuple):
                mails.append(parts[0][1])
        return mails, ids
    finally:
        with contextlib.suppress(Exception):
            box.logout()


def _mark_seen_sync(ids: list[bytes]) -> None:
    if not ids:
        return
    s = get_settings()
    box = imaplib.IMAP4_SSL(s.inbox_imap_host, s.inbox_imap_port, timeout=30)
    try:
        box.login(s.inbox_imap_user, s.inbox_password)
        box.select(s.inbox_imap_folder)
        box.store(b",".join(ids), "+FLAGS", "\\Seen")
    finally:
        with contextlib.suppress(Exception):
            box.logout()


async def fetch_alerts(sender_ok=lambda _from: True) -> tuple[InboxBatch, list[bytes]]:
    mails, ids = await asyncio.to_thread(_fetch_sync)
    alerts, unreadable = [], 0
    for raw in mails:
        try:
            head = email.message_from_bytes(raw, policy=email.policy.default)
            if not sender_ok(str(head.get("From", ""))):
                continue
            a = parse_alert(raw)
        except Exception as e:  # one broken mail never blocks the rest
            log.warning("inbox_parse_failed", error=type(e).__name__)
            unreadable += 1
            continue
        if a.listings:
            alerts.append(a)
        elif a.had_links:
            unreadable += 1  # looks like an alert but nothing came out: layout changed?
    from app.core.db import utcnow

    return InboxBatch(alerts, unreadable, utcnow()), ids


async def mark_seen(ids: list[bytes]) -> None:
    await asyncio.to_thread(_mark_seen_sync, ids)
