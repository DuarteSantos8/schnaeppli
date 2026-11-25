"""A user's own mailbox, read for Ricardo and tutti alert mails.

The simple way to get those alerts in: no extra mailbox, no forwarding filter. The user
connects the mailbox their Ricardo / tutti account already mails to, with an app
password. Schnäppli then:

* only asks the server for mails *from* the alert senders (Ricardo, tutti, Toppreise,
  Facebook; IMAP SEARCH FROM),
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
ALERT_DOMAINS = ("ricardo.ch", "tutti.ch", "toppreise.ch", "facebookmail.com")


@dataclass(frozen=True)
class Guide:
    """One step of the instructions: what to do, what you'll see, and a button to the page."""

    title: str
    detail: str = ""
    link: str | None = None
    link_label: str | None = None


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    host: str | None
    domains: tuple[str, ...]
    password_name: str  # what the provider calls the password to use
    help_url: str | None
    steps: tuple[Guide, ...]
    trouble: tuple[str, ...] = ()
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
                Guide(
                    "Turn on 2-Step Verification",
                    "Google only offers app passwords when 2-Step Verification is on. Open the page, sign in, "
                    "press “Turn on 2-Step Verification” and follow it (your phone number, then the code Google "
                    "texts you). If the page already says it's on, skip this step.",
                    "https://myaccount.google.com/signinoptions/twosv",
                    "Open 2-Step Verification",
                ),
                Guide(
                    "Create the app password",
                    "Open the next page (Google may ask for your password again). In the field “App name”, type "
                    "Schnäppli and press “Create”.",
                    "https://myaccount.google.com/apppasswords",
                    "Open app passwords",
                ),
                Guide(
                    "Copy the 16 letters",
                    "Google shows a box with 16 letters in four groups, like “abcd efgh ijkl mnop”. Copy them "
                    "(the spaces don't matter) and paste them into the field below. Google shows them only once; "
                    "if you closed the box, just create a new one.",
                ),
            ),
            (
                "“The setting you are looking for is not available for your account”: 2-Step Verification "
                "is still off (step 1), or it's a work or school account whose administrator turned app "
                "passwords off.",
                "Use your normal Gmail address above, not a second address.",
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
                Guide(
                    "Open your Apple Account",
                    "Sign in with your Apple ID, then open “Sign-In and Security”.",
                    "https://account.apple.com/account/manage",
                    "Open Apple Account",
                ),
                Guide(
                    "Create an app-specific password",
                    "Choose “App-Specific Passwords”, press “+” or “Generate”, type Schnäppli as the name and "
                    "confirm with your Apple ID password.",
                ),
                Guide(
                    "Copy it",
                    "Apple shows a password like “abcd-efgh-ijkl-mnop”. Copy it into the field below.",
                ),
            ),
            ("App-specific passwords need two-factor authentication on your Apple ID (on by default).",),
        ),
        Provider(
            "yahoo",
            "Yahoo Mail",
            "imap.mail.yahoo.com",
            ("yahoo.com", "yahoo.de", "yahoo.fr", "ymail.com"),
            "app password",
            "https://login.yahoo.com/account/security",
            (
                Guide(
                    "Open Account security",
                    "Sign in and scroll to “Generate app password” (or “Manage app passwords”).",
                    "https://login.yahoo.com/account/security",
                    "Open Yahoo security",
                ),
                Guide(
                    "Create and copy it",
                    "Type Schnäppli as the name, press “Generate password”, copy it into the field below.",
                ),
            ),
        ),
        Provider(
            "gmx",
            "GMX",
            "imap.gmx.net",
            ("gmx.ch", "gmx.net", "gmx.de", "gmx.at"),
            "password",
            "https://www.gmx.ch",
            (
                Guide(
                    "Allow access by programs",
                    "Sign in to GMX, open “Einstellungen” (settings) → “POP3/IMAP Abruf”, tick “POP3 und IMAP "
                    "Zugriff erlauben” and save.",
                    "https://www.gmx.ch",
                    "Open GMX",
                ),
                Guide("Use your GMX password", "Type your normal GMX password into the field below."),
            ),
        ),
        Provider(
            "webde",
            "WEB.DE",
            "imap.web.de",
            ("web.de",),
            "password",
            "https://web.de",
            (
                Guide(
                    "Allow access by programs",
                    "Sign in to WEB.DE, open “Einstellungen” → “POP3/IMAP Abruf”, tick “POP3 und IMAP Zugriff "
                    "erlauben” and save.",
                    "https://web.de",
                    "Open WEB.DE",
                ),
                Guide("Use your WEB.DE password", "Type your normal WEB.DE password into the field below."),
            ),
        ),
        Provider(
            "bluewin",
            "Swisscom / bluewin",
            "imaps.bluewin.ch",
            ("bluewin.ch", "bluemail.ch"),
            "password",
            None,
            (
                Guide(
                    "Use your bluewin password",
                    "Type the password of your bluewin e-mail into the field below.",
                ),
            ),
        ),
        Provider(
            "zoho",
            "Zoho Mail (paid plans)",
            "imappro.zoho.eu",
            ("zoho.eu", "zohomail.eu", "zoho.com", "zohomail.com"),
            "app password",
            "https://accounts.zoho.eu/home#security/app_password",
            (
                Guide(
                    "Turn on IMAP",
                    "In Zoho Mail open Settings → Mail Accounts → IMAP and turn IMAP access on. Zoho's free "
                    "plan has no IMAP.",
                ),
                Guide(
                    "Create an app password",
                    "Open the page, press “Generate New Password”, name it Schnäppli and copy it into the field below.",
                    "https://accounts.zoho.eu/home#security/app_password",
                    "Open Zoho security",
                ),
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
            (
                Guide(
                    "Find the IMAP server",
                    "Your provider's help pages list it (search for “IMAP settings”). Schnäppli uses port 993 "
                    "with TLS.",
                ),
                Guide(
                    "Password",
                    "Many providers want an app password for other programs; their help pages say so. "
                    "Otherwise use your normal password.",
                ),
            ),
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
        "steps": [
            {"title": g.title, "detail": g.detail, "link": g.link, "link_label": g.link_label}
            for g in p.steps
        ],
        "trouble": list(p.trouble),
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
        typ, data = box.uid("SEARCH", None, "UID", f"{last_uid + 1}:*", "SINCE", since, *_from_any())
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
        typ, data = box.uid("SEARCH", None, "SINCE", since, *_from_any())
        return len((data[0] or b"").split()) if typ == "OK" else 0
    finally:
        with contextlib.suppress(Exception):
            box.logout()


def _from_any() -> list[str]:
    """IMAP search keys: FROM any of the alert domains (OR is binary in IMAP, so it nests)."""
    keys = ["FROM", f'"{ALERT_DOMAINS[-1]}"']
    for d in reversed(ALERT_DOMAINS[:-1]):
        keys = ["OR", "FROM", f'"{d}"', *keys]
    return keys


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
