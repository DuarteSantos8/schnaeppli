"""A user's own mailbox, read for Ricardo and tutti alert mails.

The simple way to get those alerts in: no extra mailbox, no forwarding filter. The user
connects the mailbox their Ricardo / tutti account already mails to, with an app
password. Schnäppli then:

* only asks the server for mails *from* ricardo.ch and tutti.ch (IMAP SEARCH FROM),
  and checks the sender again on its side;
* opens the folder read-only (EXAMINE) and fetches with BODY.PEEK, so nothing in the
  mailbox changes, not even the "read" mark;
* remembers the highest UID it has seen, so every mail is read once.

Only IMAP over TLS on port 993, and only to public addresses.
"""

from __future__ import annotations

import asyncio
import contextlib
import email
import email.policy
import imaplib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parseaddr

import structlog

from app.core.safe_http import UnsafeURL, _assert_public
from app.sources.inbox import ParsedAlert, parse_alert

log = structlog.get_logger()
LOOKBACK_DAYS = 14
MAX_PER_CHECK = 60
ALERT_DOMAINS = ("ricardo.ch", "tutti.ch")


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    host: str | None
    domains: tuple[str, ...]
    password_name: str  # what the provider calls the password to use
    help_url: str | None
    steps: tuple[str, ...]
    supported: bool = True


PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in [
        Provider(
            "gmail",
            "Gmail / Google Workspace",
            "imap.gmail.com",
            ("gmail.com", "googlemail.com"),
            "app password",
            "https://myaccount.google.com/apppasswords",
            (
                "Turn on 2-Step Verification for your Google account, if it isn't on yet.",
                "Open the app passwords page, name it “Schnäppli” and create it.",
                "Copy the 16-letter password and paste it here.",
            ),
        ),
        Provider(
            "icloud",
            "iCloud Mail",
            "imap.mail.me.com",
            ("icloud.com", "me.com", "mac.com"),
            "app-specific password",
            "https://account.apple.com/account/manage",
            (
                "Sign in to your Apple Account and open Sign-In and Security → App-Specific Passwords.",
                "Create one named “Schnäppli”.",
                "Paste it here.",
            ),
        ),
        Provider(
            "yahoo",
            "Yahoo Mail",
            "imap.mail.yahoo.com",
            ("yahoo.com", "yahoo.de", "yahoo.fr", "ymail.com"),
            "app password",
            "https://login.yahoo.com/account/security",
            ("Open Account security → Generate app password.", "Name it “Schnäppli” and paste it here."),
        ),
        Provider(
            "gmx",
            "GMX",
            "imap.gmx.net",
            ("gmx.ch", "gmx.net", "gmx.de", "gmx.at"),
            "password",
            "https://www.gmx.ch",
            (
                "In GMX, open Settings → POP3/IMAP and allow access by other programs.",
                "Use your normal GMX password (or an app password, if you set one up).",
            ),
        ),
        Provider(
            "webde",
            "WEB.DE",
            "imap.web.de",
            ("web.de",),
            "password",
            "https://web.de",
            ("In WEB.DE, open Settings → POP3/IMAP and allow access.", "Use your WEB.DE password."),
        ),
        Provider(
            "bluewin",
            "Swisscom / bluewin",
            "imaps.bluewin.ch",
            ("bluewin.ch", "bluemail.ch"),
            "password",
            None,
            ("Use your bluewin e-mail password.",),
        ),
        Provider(
            "zoho",
            "Zoho Mail (paid plans)",
            "imappro.zoho.eu",
            ("zoho.eu", "zohomail.eu", "zoho.com", "zohomail.com"),
            "app password",
            "https://accounts.zoho.eu/home#security/app_password",
            (
                "Zoho's free plan has no IMAP; paid plans do. Turn on IMAP access in Mail settings.",
                "Create an app password named “Schnäppli” and paste it here.",
            ),
        ),
        Provider(
            "outlook",
            "Outlook.com / Hotmail",
            None,
            ("outlook.com", "hotmail.com", "hotmail.ch", "live.com", "live.de", "msn.com"),
            "",
            None,
            (),
            supported=False,
        ),
        Provider(
            "proton",
            "Proton Mail",
            None,
            ("proton.me", "protonmail.com", "protonmail.ch", "pm.me"),
            "",
            None,
            (),
            supported=False,
        ),
        Provider(
            "other",
            "Another provider",
            None,
            (),
            "password",
            None,
            ("Ask your provider for its IMAP server and whether it needs an app password.",),
        ),
    ]
}

UNSUPPORTED_TEXT = {
    "outlook": "Microsoft only lets other apps into Outlook.com mailboxes with its own sign-in, "
    "not with a password, so Schnäppli can't read it. Let Ricardo and tutti mail another "
    "address (e.g. Gmail), or forward their mails there.",
    "proton": "Proton Mail is encrypted and only reachable through the Proton Mail Bridge app on "
    "your computer. Let Ricardo and tutti mail another address, or forward their mails there.",
}


def guess_provider(address: str) -> str:
    domain = address.rpartition("@")[2].strip().lower()
    for p in PROVIDERS.values():
        if domain in p.domains:
            return p.id
    return "other"


def provider_out(p: Provider) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "host": p.host,
        "domains": list(p.domains),
        "password_name": p.password_name,
        "help_url": p.help_url,
        "steps": list(p.steps),
        "supported": p.supported,
        "unsupported_text": UNSUPPORTED_TEXT.get(p.id),
    }


class MailboxError(Exception):
    """Something the user can fix; `kind` is "login" (wrong password) or "error"."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind


@dataclass
class Account:
    host: str
    username: str
    password: str
    port: int = 993
    folder: str = "INBOX"


@dataclass
class MailBatch:
    alerts: list[ParsedAlert]
    unreadable: int
    uidvalidity: int | None
    last_uid: int


def _sender_is_alert(raw_from: str) -> bool:
    addr = parseaddr(raw_from)[1].lower()
    return any(addr.endswith(("@" + d, "." + d)) for d in ALERT_DOMAINS)


_UIDVALIDITY = re.compile(rb"UIDVALIDITY (\d+)")


def _open(acc: Account) -> imaplib.IMAP4_SSL:
    try:
        box = imaplib.IMAP4_SSL(acc.host, acc.port, timeout=30)
    except (TimeoutError, OSError) as e:
        raise MailboxError(f"Couldn't reach {acc.host}. Check the server name.") from e
    try:
        box.login(acc.username, acc.password)
    except imaplib.IMAP4.error as e:
        with contextlib.suppress(Exception):
            box.logout()
        raise MailboxError(
            "The mailbox refused the sign-in. Check the address and the password.", "login"
        ) from e
    return box


def _uidvalidity(box: imaplib.IMAP4_SSL) -> int | None:
    _typ, data = box.response("UIDVALIDITY")
    if data and data[0]:
        with contextlib.suppress(ValueError, TypeError):
            return int(data[0])
    return None


def _fetch_sync(acc: Account, uidvalidity: int | None, last_uid: int) -> MailBatch:
    box = _open(acc)
    try:
        typ, _ = box.select(_quote(acc.folder), readonly=True)  # EXAMINE: nothing gets marked
        if typ != "OK":
            raise MailboxError(f"The folder “{acc.folder}” doesn't exist.")
        valid = _uidvalidity(box)
        if uidvalidity is not None and valid is not None and valid != uidvalidity:
            last_uid = 0  # the server renumbered its mails: look at the recent ones again
        since = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")
        typ, data = box.uid(
            "SEARCH", None, "UID", f"{last_uid + 1}:*", "SINCE", since,
            "OR", "FROM", '"ricardo.ch"', "FROM", '"tutti.ch"',
        )  # fmt: skip
        uids = sorted(int(u) for u in (data[0] or b"").split()) if typ == "OK" else []
        uids = [u for u in uids if u > last_uid][:MAX_PER_CHECK]  # "n:*" always returns the newest one
        alerts, unreadable, newest = [], 0, last_uid
        for uid in uids:
            newest = max(newest, uid)
            typ, parts = box.uid("FETCH", str(uid), "(BODY.PEEK[])")
            raw = next((p[1] for p in parts or [] if isinstance(p, tuple)), None) if typ == "OK" else None
            if not raw:
                continue
            try:
                head = email.message_from_bytes(raw, policy=email.policy.default)
                if not _sender_is_alert(str(head.get("From", ""))):
                    continue
                a = parse_alert(raw)
            except Exception as e:  # one broken mail never blocks the rest
                log.warning("mailbox_parse_failed", error=type(e).__name__)
                unreadable += 1
                continue
            if a.listings:
                alerts.append(a)
            elif a.had_links:
                unreadable += 1
        return MailBatch(alerts, unreadable, valid, newest)
    finally:
        with contextlib.suppress(Exception):
            box.logout()


def _test_sync(acc: Account) -> int:
    """Signs in and counts alert mails from the last 14 days."""
    box = _open(acc)
    try:
        typ, _ = box.select(_quote(acc.folder), readonly=True)
        if typ != "OK":
            raise MailboxError(f"The folder “{acc.folder}” doesn't exist.")
        since = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")
        typ, data = box.uid(
            "SEARCH", None, "SINCE", since, "OR", "FROM", '"ricardo.ch"', "FROM", '"tutti.ch"'
        )
        return len((data[0] or b"").split()) if typ == "OK" else 0
    finally:
        with contextlib.suppress(Exception):
            box.logout()


def _quote(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


async def _check_host(host: str) -> None:
    try:
        await _assert_public(host)
    except UnsafeURL as e:
        raise MailboxError(f"{host}: {e}") from e


async def test(acc: Account) -> int:
    await _check_host(acc.host)
    return await asyncio.to_thread(_test_sync, acc)


async def fetch(acc: Account, uidvalidity: int | None, last_uid: int) -> MailBatch:
    await _check_host(acc.host)
    return await asyncio.to_thread(_fetch_sync, acc, uidvalidity, last_uid)
