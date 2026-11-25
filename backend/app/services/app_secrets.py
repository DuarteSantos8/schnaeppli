"""Instance-wide keys the administrator enters in the browser (Setup), stored encrypted.

Values from the server configuration (secret files / env) win over the stored ones, so
existing installs keep working. Each process keeps a copy in memory; `refresh` reloads
it, and is called before anything that uses the keys."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import secret_box
from app.models import AppSetting

log = structlog.get_logger()
EBAY_KEY = "ebay_credentials"
_ebay_db: tuple[str, str] | None = None


async def refresh(db: AsyncSession) -> None:
    global _ebay_db
    row = await db.get(AppSetting, EBAY_KEY)
    if not row or not row.value.get("client_id"):
        _ebay_db = None
        return
    try:
        secret = secret_box().decrypt(row.value["secret"], "app:ebay")
    except Exception:  # wrong key after a restore etc.: treat as missing, never crash a run
        log.warning("ebay_credentials_unreadable")
        _ebay_db = None
        return
    _ebay_db = (row.value["client_id"], secret)


def ebay_from_config() -> bool:
    s = get_settings()
    return bool(s.ebay_client_id and s.ebay_client_secret)


def ebay_credentials() -> tuple[str, str] | None:
    s = get_settings()
    if s.ebay_client_id and s.ebay_client_secret:
        return s.ebay_client_id, s.ebay_client_secret
    return _ebay_db


async def save_ebay(db: AsyncSession, client_id: str, secret: str | None) -> None:
    row = await db.get(AppSetting, EBAY_KEY)
    if secret is None:
        if row:
            await db.delete(row)
    else:
        value = {"client_id": client_id, "secret": secret_box().encrypt(secret, "app:ebay")}
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=EBAY_KEY, value=value))
    await db.flush()
    await refresh(db)
