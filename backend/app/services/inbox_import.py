"""Turns Ricardo / tutti alert mails into matches for the right searches."""

from __future__ import annotations

import re
import unicodedata
import uuid
from email.utils import parseaddr

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.security import secret_box
from app.models import AppSetting, MailConnection, SearchProfile, User
from app.services import listings as listing_svc
from app.services.runner import queries_for
from app.sources import inbox, mailbox
from app.sources.inbox import ParsedAlert

log = structlog.get_logger()
STATUS_KEY = "inbox_status"
STOP = {
    "und",
    "oder",
    "mit",
    "für",
    "fur",
    "the",
    "and",
    "for",
    "with",
    "von",
    "der",
    "die",
    "das",
    "ein",
    "eine",
    "neu",
    "new",
}


def _tokens(text: str) -> set[str]:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]+", t) if len(w) > 1 and w not in STOP}


def route(alert: ParsedAlert, title: str, searches: list[SearchProfile]) -> list[SearchProfile]:
    """Searches this listing belongs to: the saved-search name and the title are compared
    with each search's own queries. A query counts when most of its words appear."""
    have = _tokens(f"{alert.search_name} {title}")
    scored = []
    for s in searches:
        cfg = (s.sources or {}).get(alert.site or "", {})
        if cfg.get("enabled", True) is False:
            continue
        best = 0.0
        for q in queries_for(s) + [s.title]:
            want = _tokens(q)
            if want:
                best = max(best, len(want & have) / len(want))
        scored.append((best, s))
    strong = [s for score, s in scored if score >= 0.6]
    if strong:
        return strong
    scored.sort(key=lambda x: x[0], reverse=True)
    return [scored[0][1]] if scored and scored[0][0] >= 0.34 else []


async def _owner(db: AsyncSession) -> User | None:
    email = get_settings().inbox_owner_email.strip().lower()
    q = select(User).where(User.is_active.is_(True))
    q = q.where(User.email == email) if email else q.where(User.is_admin.is_(True)).order_by(User.created_at)
    return (await db.scalars(q.limit(1))).first()


async def status(db: AsyncSession) -> dict:
    row = await db.get(AppSetting, STATUS_KEY)
    return dict(row.value) if row else {}


async def _save_status(db: AsyncSession, value: dict) -> None:
    row = await db.get(AppSetting, STATUS_KEY)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=STATUS_KEY, value=value))


def _sender_ok(raw_from: str) -> bool:
    allowed = [a.strip().lower() for a in get_settings().inbox_allowed_senders.split(",") if a.strip()]
    if not allowed:
        return True
    addr = parseaddr(raw_from)[1].lower()
    return addr.endswith(("@ricardo.ch", ".ricardo.ch", "@tutti.ch", ".tutti.ch")) or addr in allowed


async def _store(
    db: AsyncSession, owner: User, alerts: list[ParsedAlert]
) -> tuple[list[uuid.UUID], int, int, dict[str, int]]:
    """Puts the listings of these alerts into the owner's matching searches."""
    searches = (
        await db.scalars(
            select(SearchProfile).where(SearchProfile.user_id == owner.id, SearchProfile.status == "active")
        )
    ).all()
    to_analyse: list[uuid.UUID] = []
    imported = unrouted = 0
    by_site: dict[str, int] = {}
    for alert in alerts:
        for raw in alert.listings:
            targets = route(alert, raw.title, list(searches))
            if not targets:
                unrouted += 1
                continue
            listing, _new, previous = await listing_svc.upsert_listing(db, raw)
            for search in targets:
                match, created = await listing_svc.ensure_match(db, owner, search, listing, previous)
                await db.flush()
                if created:
                    imported += 1
                    by_site[raw.source] = by_site.get(raw.source, 0) + 1
                    if match.analysis_state == "queued":
                        to_analyse.append(match.id)
    return to_analyse, imported, unrouted, by_site


def account_for(conn: MailConnection) -> mailbox.Account:
    password = secret_box().decrypt(conn.encrypted_password, f"mail:{conn.id}")
    return mailbox.Account(conn.imap_host, conn.username, password, conn.imap_port, conn.folder)


async def import_user_mail(db: AsyncSession, conn: MailConnection) -> list[uuid.UUID]:
    """One user's own mailbox: new Ricardo / tutti alert mails → their searches."""
    now = utcnow()
    stats = dict(conn.stats or {})
    try:
        batch = await mailbox.fetch(account_for(conn), conn.uidvalidity, conn.last_uid)
    except mailbox.MailboxError as e:
        conn.state, conn.state_detail, conn.checked_at = e.kind, str(e)[:300], now
        await db.commit()
        return []
    except Exception as e:  # network trouble, server quirks: try again next time
        conn.state, conn.checked_at = "error", now
        conn.state_detail = f"Couldn't read the mailbox ({type(e).__name__})."
        await db.commit()
        log.warning("mailbox_check_failed", error=type(e).__name__)
        return []
    owner = await db.get(User, conn.user_id)
    to_analyse, imported, unrouted, by_site = (
        await _store(db, owner, batch.alerts) if owner and owner.is_active else ([], 0, 0, {})
    )
    totals = dict(stats.get("totals", {}))
    for k, v in by_site.items():
        totals[k] = totals.get(k, 0) + v
    names = list(stats.get("search_names", []))
    for a in batch.alerts:
        if a.search_name and a.search_name not in names:
            names.append(a.search_name)
    conn.stats = stats | {
        "totals": totals,
        "mails_total": stats.get("mails_total", 0) + len(batch.alerts),
        "imported": imported,
        "unrouted": unrouted,
        "unreadable": batch.unreadable,
        "search_names": names[-20:],
    }
    conn.uidvalidity, conn.last_uid = batch.uidvalidity, batch.last_uid
    conn.state, conn.state_detail, conn.checked_at = "ok", None, now
    if batch.alerts:
        conn.last_alert_at = now
    await db.commit()
    if imported or unrouted:
        log.info("mailbox_imported", imported=imported, unrouted=unrouted)
    return to_analyse


async def import_all(db: AsyncSession) -> list[uuid.UUID]:
    """The administrator's shared inbox (if configured) and every connected user mailbox."""
    ids = await import_alerts(db)
    conns = (await db.scalars(select(MailConnection).where(MailConnection.enabled.is_(True)))).all()
    for conn in conns:
        ids += await import_user_mail(db, conn)
    return ids


async def import_alerts(db: AsyncSession) -> list[uuid.UUID]:
    """Reads new alert mails and returns the ids of new matches to analyse."""
    if not inbox.configured():
        return []
    prev = await status(db)
    st = {"checked_at": utcnow().isoformat(), "totals": prev.get("totals", {})}
    try:
        batch, ids = await inbox.fetch_alerts(sender_ok=_sender_ok)
    except Exception as e:  # IMAP down, wrong password, ...
        st |= {"error": f"{type(e).__name__}: {str(e)[:160]}", "last_ok_at": prev.get("last_ok_at")}
        await _save_status(db, st)
        await db.commit()
        log.warning("inbox_check_failed", error=type(e).__name__)
        return []

    owner = await _owner(db)
    to_analyse, imported, unrouted, by_site = (
        await _store(db, owner, batch.alerts) if owner else ([], 0, 0, {})
    )
    totals = dict(st["totals"])
    for k, v in by_site.items():
        totals[k] = totals.get(k, 0) + v
    st |= {
        "error": None,
        "last_ok_at": st["checked_at"],
        "mails": len(batch.alerts),
        "imported": imported,
        "unrouted": unrouted,
        "unreadable": batch.unreadable,
        "totals": totals,
        "last_alert_at": st["checked_at"] if batch.alerts else prev.get("last_alert_at"),
        "last_search_names": [a.search_name for a in batch.alerts][-5:] or prev.get("last_search_names", []),
    }
    await _save_status(db, st)
    await db.commit()
    await inbox.mark_seen(ids)  # only after the matches are stored
    if imported or unrouted:
        log.info("inbox_imported", imported=imported, unrouted=unrouted)
    return to_analyse
