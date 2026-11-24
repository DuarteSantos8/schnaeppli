"""Crash recovery: notice when the server was down, catch up, and say so.

The worker writes a heartbeat to the database every minute and a "clean" mark when
it stops normally. When it starts again and the last heartbeat is older than a few
minutes, the server was offline (a crash, power loss or a long planned restart).
It then:

* marks search runs that were interrupted mid-way as failed and runs those searches
  again right away,
* lets the scheduler pick up every search whose run time passed while it was down
  (one catch-up run per search, not one per missed slot),
* sends digests whose time passed during the outage, late (the newest missed slot,
  covering everything since the previous digest),
* re-queues listing analyses that were waiting (the worker does this right after),
* and tells the administrators what happened: on Telegram when linked, and on Home.
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.models import AppSetting, SearchMatch, SearchProfile, SearchRun, User
from app.services import notify

log = structlog.get_logger()

HEARTBEAT_KEY = "worker_heartbeat"
OUTAGE_KEY = "last_outage"
#: A gap longer than this between heartbeats counts as an outage (ticks are 1 min apart;
#: a normal redeploy takes well under this).
OUTAGE_AFTER = timedelta(minutes=4)
#: Digests missed by up to this long are still sent after a restart; older ones are skipped.
DIGEST_CATCHUP_LIMIT = timedelta(hours=12)
#: A run still "running" after this long can't still be running.
RUN_STUCK_AFTER = timedelta(minutes=20)


async def _get(db: AsyncSession, key: str) -> dict | None:
    row = await db.get(AppSetting, key)
    return dict(row.value) if row else None


async def _put(db: AsyncSession, key: str, value: dict) -> None:
    row = await db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


async def heartbeat(db: AsyncSession, now: datetime | None = None, clean: bool = False) -> None:
    now = now or utcnow()
    await _put(db, HEARTBEAT_KEY, {"at": now.isoformat(), "clean": clean})
    await db.commit()


def _fmt_duration(d: timedelta) -> str:
    mins = int(d.total_seconds() // 60)
    if mins < 60:
        return f"{mins} min"
    h, m = divmod(mins, 60)
    if h < 48:
        return f"{h} h {m} min" if m else f"{h} h"
    return f"{h // 24} days {h % 24} h"


async def recover(db: AsyncSession, now: datetime | None = None) -> dict | None:
    """Run once when the worker starts. Returns the outage report, or None if there was none."""
    now = now or utcnow()
    beat = await _get(db, HEARTBEAT_KEY)
    # Interrupted runs are cleaned up after every start, outage or not.
    stuck = (
        await db.scalars(
            select(SearchRun).where(
                SearchRun.status == "running", SearchRun.started_at < now - RUN_STUCK_AFTER
            )
        )
    ).all()
    restarted: list[str] = []
    for run in stuck:
        run.status = "failed"
        run.finished_at = now
        run.error = "Interrupted: the server stopped during this run. It was started again."
        search = await db.get(SearchProfile, run.search_id)
        if search and search.status == "active":
            search.next_run_at = now
            restarted.append(search.title)
    await db.commit()

    if not beat:
        await heartbeat(db, now)
        return None
    last = datetime.fromisoformat(beat["at"])
    gap = now - last
    if gap < OUTAGE_AFTER:
        await heartbeat(db, now)
        return None

    overdue = await db.scalar(
        select(func.count())
        .select_from(SearchProfile)
        .where(SearchProfile.status == "active", SearchProfile.next_run_at <= now)
    )
    waiting = await db.scalar(
        select(func.count()).select_from(SearchMatch).where(SearchMatch.analysis_state == "queued")
    )
    report = {
        "from": last.isoformat(),
        "to": now.isoformat(),
        "minutes": int(gap.total_seconds() // 60),
        "clean": bool(beat.get("clean")),
        "searches_caught_up": int(overdue or 0),
        "runs_restarted": restarted,
        "analyses_requeued": int(waiting or 0),
        "digests_late": 0,
    }
    await _put(db, OUTAGE_KEY, report)
    await heartbeat(db, now)
    log.warning("outage_detected", minutes=report["minutes"], clean=report["clean"])
    return report


def digest_window(report: dict | None) -> int:
    """Minutes of digest slots to honour on the first tick(s) after a restart."""
    if not report:
        return 5
    return int(min(report["minutes"] + 5, DIGEST_CATCHUP_LIMIT.total_seconds() // 60))


def report_text(r: dict, tz_name: str = "Europe/Zurich") -> str:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    a = datetime.fromisoformat(r["from"]).astimezone(tz)
    b = datetime.fromisoformat(r["to"]).astimezone(tz)
    span = f"{a:%d.%m. %H:%M} – {b:%H:%M}" if a.date() == b.date() else f"{a:%d.%m. %H:%M} – {b:%d.%m. %H:%M}"
    cause = (
        "It was shut down normally (a planned restart or update)."
        if r["clean"]
        else "It stopped without shutting down, so the server most likely crashed, froze or lost power."
    )
    lines = [
        "<b>Schnäppli was offline</b>",
        f"{span} ({_fmt_duration(timedelta(minutes=r['minutes']))}). {cause}",
        "",
        "Caught up since:",
        f"• {r['searches_caught_up']} search(es) ran again"
        if r["searches_caught_up"]
        else "• No searches were due",
    ]
    if r["runs_restarted"]:
        names = ", ".join(html.escape(t) for t in r["runs_restarted"][:5])
        lines.append(f"• Restarted interrupted run(s): {names}")
    if r["analyses_requeued"]:
        lines.append(f"• {r['analyses_requeued']} waiting listing analyses queued again")
    lines.append("• Digests that fell into the outage are sent now, late")
    lines += ["", "Your data is in the database and in the regular backups; nothing needs doing."]
    return "\n".join(lines)


async def send_report(db: AsyncSession, r: dict) -> int:
    """Tell every administrator. Returns how many were told on Telegram."""
    admins = (await db.scalars(select(User).where(User.is_admin.is_(True), User.is_active.is_(True)))).all()
    told = 0
    for u in admins:
        key = f"outage:{r['to']}"
        await notify._send_simple(
            db, u, "outage_report", "Server was offline", report_text(r, u.timezone), key
        )
        told += 1
    return told


async def last_outage(db: AsyncSession) -> dict | None:
    return await _get(db, OUTAGE_KEY)
