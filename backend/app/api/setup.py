"""Setup in the browser: the guided steps, the user's own mailbox, the eBay key."""

from __future__ import annotations

import base64
import time
from collections import defaultdict, deque

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import admin_user, audit, current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.jobs import enqueue
from app.core.security import key_hint, secret_box
from app.models import CustomShop, MailConnection, ProviderCredential, SearchProfile, TelegramLink, User
from app.services import app_secrets, inbox_import, telegram
from app.sources import inbox, mailbox
from app.sources.ebay import HOSTS, SCOPE

router = APIRouter(prefix="/api/setup", tags=["setup"])

# Sign-in attempts against mail servers, per user: Schnäppli must not become a password-guessing tool.
_attempts: dict[str, deque[float]] = defaultdict(deque)
MAX_ATTEMPTS, WINDOW = 8, 3600


def _limit(key: str) -> None:
    q, now = _attempts[key], time.monotonic()
    while q and now - q[0] > WINDOW:
        q.popleft()
    if len(q) >= MAX_ATTEMPTS:
        raise HTTPException(429, "Too many attempts. Try again in an hour.")
    q.append(now)


# --------------------------------------------------------------------- mailbox
class MailIn(BaseModel):
    address: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=500)
    provider: str | None = Field(None, max_length=20)
    host: str | None = Field(None, max_length=255)
    folder: str | None = Field(None, max_length=120)


class MailPatch(BaseModel):
    enabled: bool


def mail_out(c: MailConnection | None) -> dict | None:
    if c is None:
        return None
    p = mailbox.PROVIDERS.get(c.provider)
    st = c.stats or {}
    return {
        "provider": c.provider,
        "provider_name": p.name if p else c.provider,
        "address": c.username,
        "host": c.imap_host,
        "folder": c.folder,
        "enabled": c.enabled,
        "state": c.state,
        "state_detail": c.state_detail,
        "checked_at": c.checked_at.isoformat() if c.checked_at else None,
        "last_alert_at": c.last_alert_at.isoformat() if c.last_alert_at else None,
        "totals": st.get("totals", {}),
        "mails_total": st.get("mails_total", 0),
        "unrouted": st.get("unrouted", 0),
        "unreadable": st.get("unreadable", 0),
        "search_names": st.get("search_names", []),
    }


async def _mine(db: AsyncSession, user: User) -> MailConnection | None:
    return await db.scalar(select(MailConnection).where(MailConnection.user_id == user.id))


@router.get("/mail")
async def get_mail(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return {
        "connection": mail_out(await _mine(db, user)),
        "providers": [mailbox.provider_out(p) for p in mailbox.PROVIDERS.values()],
        "shared_inbox": inbox.configured(),
    }


@router.post("/mail")
async def connect_mail(
    body: MailIn, request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Signs in once to check the details, then saves them (the password encrypted)."""
    address = body.address.strip()
    if "@" not in address:
        raise HTTPException(422, "Enter your full e-mail address.")
    pid = body.provider or mailbox.guess_provider(address)
    p = mailbox.PROVIDERS.get(pid)
    if p is None:
        raise HTTPException(422, "Unknown provider.")
    if not p.supported:
        raise HTTPException(422, mailbox.UNSUPPORTED_TEXT.get(pid, "This provider can't be connected."))
    host = (body.host or p.host or "").strip().lower()
    if not host or "/" in host or ":" in host or " " in host:
        raise HTTPException(422, "Enter the IMAP server of your provider, e.g. imap.example.ch.")
    folder = (body.folder or "INBOX").strip() or "INBOX"
    password = body.password.strip() if pid == "gmail" else body.password
    if pid == "gmail":
        password = password.replace(" ", "")  # Google shows app passwords in groups of four

    _limit(str(user.id))
    names = [address]
    if pid == "icloud":
        names.append(address.split("@")[0])  # iCloud sometimes wants only the name part
    found, used, last_err = None, address, None
    for name in names:
        try:
            found = await mailbox.test(mailbox.Account(host, name, password, 993, folder))
            used = name
            break
        except mailbox.MailboxError as e:
            last_err = e
            if e.kind != "login":
                break
    if found is None:
        assert last_err
        hint = ""
        if last_err.kind == "login" and p.password_name and p.password_name != "password":  # noqa: S105 (a label, not a secret)
            hint = f" {p.name} needs an {p.password_name} here, not your normal password."
        raise HTTPException(422, str(last_err) + hint)

    conn = await _mine(db, user)
    if conn is None:
        conn = MailConnection(
            user_id=user.id, provider=pid, username=used, imap_host=host, encrypted_password=""
        )
        db.add(conn)
        await db.flush()
    elif (conn.imap_host, conn.username, conn.folder) != (host, used, folder):
        conn.uidvalidity, conn.last_uid, conn.stats, conn.last_alert_at = None, 0, {}, None
    conn.provider, conn.username, conn.imap_host, conn.imap_port, conn.folder = pid, used, host, 993, folder
    conn.encrypted_password = secret_box().encrypt(password, f"mail:{conn.id}")
    conn.enabled, conn.state, conn.state_detail = True, "ok", None
    await audit(db, request, "mail_connected", user.id, host)
    await db.commit()
    return {"connection": mail_out(conn), "found": found}


@router.post("/mail/check")
async def check_mail(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Reads new alert mails now instead of waiting for the next five-minute check."""
    conn = await _mine(db, user)
    if conn is None:
        raise HTTPException(404, "No mailbox connected.")
    _limit(f"check:{user.id}")
    before = sum((conn.stats or {}).get("totals", {}).values())
    ids = await inbox_import.import_user_mail(db, conn)
    for mid in ids:
        await enqueue("analyze_match_job", mid, job_id=f"analyze:{mid}")
    after = sum((conn.stats or {}).get("totals", {}).values())
    return {"connection": mail_out(conn), "imported": after - before}


@router.patch("/mail")
async def patch_mail(body: MailPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    conn = await _mine(db, user)
    if conn is None:
        raise HTTPException(404, "No mailbox connected.")
    conn.enabled = body.enabled
    await db.commit()
    return mail_out(conn)


@router.delete("/mail", status_code=204)
async def disconnect_mail(
    request: Request, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    conn = await _mine(db, user)
    if conn is not None:
        await db.delete(conn)
        await audit(db, request, "mail_disconnected", user.id)
        await db.commit()


# ------------------------------------------------------------------------ eBay
class EbayIn(BaseModel):
    client_id: str = Field(min_length=10, max_length=200)
    client_secret: str = Field(min_length=10, max_length=200)


async def ebay_state() -> dict:
    creds = app_secrets.ebay_credentials()
    return {
        "configured": creds is not None,
        "from_config": app_secrets.ebay_from_config(),
        "client_id_hint": key_hint(creds[0]) if creds else None,
    }


@router.get("/ebay")
async def get_ebay(user: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    await app_secrets.refresh(db)
    return await ebay_state()


@router.put("/ebay")
async def put_ebay(
    body: EbayIn, request: Request, user: User = Depends(admin_user), db: AsyncSession = Depends(get_db)
):
    """Checks the key with eBay (one token request), then stores it encrypted."""
    if app_secrets.ebay_from_config():
        raise HTTPException(409, "eBay is set up in the server configuration; change it there.")
    _limit(f"ebay:{user.id}")
    cid, secret = body.client_id.strip(), body.client_secret.strip()
    if "SBX" in cid.upper():
        raise HTTPException(422, "That's a Sandbox key. Use the Production keyset.")
    base = HOSTS.get(get_settings().ebay_environment, HOSTS["production"])
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{base}/identity/v1/oauth2/token",
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials", "scope": SCOPE},
            )
    except httpx.HTTPError as e:
        raise HTTPException(502, "eBay couldn't be reached. Try again in a moment.") from e
    if resp.status_code in (400, 401):
        raise HTTPException(
            422, "eBay didn't accept this key. Copy the App ID and Cert ID of the Production keyset."
        )
    if resp.status_code >= 300:
        raise HTTPException(502, f"eBay answered {resp.status_code}. Try again later.")
    await app_secrets.save_ebay(db, cid, secret)
    await audit(db, request, "ebay_key_saved", user.id)
    await db.commit()
    return await ebay_state()


@router.delete("/ebay")
async def delete_ebay(request: Request, user: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    await app_secrets.save_ebay(db, "", None)
    await audit(db, request, "ebay_key_removed", user.id)
    await db.commit()
    return await ebay_state()


# ---------------------------------------------------------------------- steps
@router.get("")
async def overview(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Which setup steps are done, for the guide and the card on Home."""
    await app_secrets.refresh(db)
    s = get_settings()
    conn = await _mine(db, user)
    link = await db.scalar(select(TelegramLink).where(TelegramLink.user_id == user.id))
    has_ai = await db.scalar(
        select(ProviderCredential.id).where(ProviderCredential.user_id == user.id).limit(1)
    )
    shared_ai = await db.scalar(
        select(ProviderCredential.id).where(ProviderCredential.user_id.is_(None)).limit(1)
    )
    searches = await db.scalar(select(SearchProfile.id).where(SearchProfile.user_id == user.id).limit(1))
    shops = await db.scalar(select(CustomShop.id).where(CustomShop.user_id == user.id).limit(1))
    return {
        "is_admin": user.is_admin,
        "ai": bool(has_ai or shared_ai),
        "claude_code_available": bool(
            user.is_admin and s.claude_code_bridge_url and s.claude_code_bridge_secret
        ),
        "location": user.lat is not None,
        "mail": mail_out(conn),
        "shared_inbox": inbox.configured(),
        "alerts_arrived": bool(conn and conn.last_alert_at)
        or bool(inbox.configured() and (await inbox_import.status(db)).get("last_alert_at")),
        "search": bool(searches),
        "telegram_configured": telegram.configured(),
        "telegram": bool(link and link.chat_id),
        "ebay": await ebay_state(),
        "shops": bool(shops),
    }
