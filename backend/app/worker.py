"""Background worker (arq). Three independent job types:

1. ``run_search_job``   collect listings (no AI)
2. ``analyze_match_job`` evaluate one match (AI, budget-gated, cached)
3. ``digest_job``        summarise existing results (no listing analysis)

A cron tick every minute enqueues due searches and digests. The Telegram bot
runs as a long-polling task inside the worker (outbound only).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

import structlog
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import sessionmaker, utcnow
from app.core.logging import setup_logging
from app.models import SearchMatch, SearchProfile, User
from app.services import analysis, digest, notify, resilience, telegram
from app.services.runner import run_search
from app.services.schedule import digest_due, next_search_run

log = structlog.get_logger()


async def run_search_job(ctx, search_id: str) -> dict:
    async with sessionmaker()() as db:
        try:
            run, match_ids = await run_search(db, uuid.UUID(search_id))
        except ValueError:
            return {"skipped": "search gone"}
        search = await db.get(SearchProfile, run.search_id)
        if run.status == "failed" and search:
            user = await db.get(User, search.user_id)
            if user:
                await notify.notify_search_failure(db, user, search, run.error or "unknown error")
    for mid in match_ids:
        await ctx["redis"].enqueue_job("analyze_match_job", str(mid), _job_id=f"analyze:{mid}")
    return {"run": str(run.id), "status": run.status, "queued_analyses": len(match_ids)}


async def analyze_match_job(ctx, match_id: str) -> dict:
    async with sessionmaker()() as db:
        try:
            match = await analysis.analyze_match(db, uuid.UUID(match_id))
        except Exception as e:  # retryable provider errors
            log.warning("analysis_retry", match_id=match_id, error=str(e))
            raise
        if match is None:
            return {"skipped": True}
        if match.analysis_state == "done":
            await notify.maybe_alert_deal(db, match)
            await notify.maybe_alert_price_drop(db, match)
        return {"state": match.analysis_state, "score": match.deal_score}


async def digest_job(ctx, user_id: str, slot: str) -> str:
    async with sessionmaker()() as db:
        return await digest.send_digest(db, uuid.UUID(user_id), slot)


async def tick(ctx) -> None:
    now = utcnow()
    window = 5
    if ctx.get("catchup_ticks", 0) > 0:  # the first ticks after an outage also send missed digests
        ctx["catchup_ticks"] -= 1
        window = ctx.get("digest_window", 5)
    async with sessionmaker()() as db:
        await resilience.heartbeat(db, now)
        due = (
            await db.scalars(
                select(SearchProfile)
                .where(SearchProfile.status == "active", SearchProfile.next_run_at <= now)
                .order_by(SearchProfile.priority, SearchProfile.next_run_at)
                .limit(50)
            )
        ).all()
        for s in due:
            user = await db.get(User, s.user_id)
            if not user or not user.is_active:
                continue
            # Move next_run_at forward first so a slow run can't be enqueued twice.
            s.next_run_at = next_search_run(s, user, now)
            await db.commit()
            await ctx["redis"].enqueue_job(
                "run_search_job", str(s.id), _job_id=f"run:{s.id}:{now:%Y%m%d%H%M}"
            )
        # Searches that never got a next_run_at (e.g. after an upgrade)
        missing = (
            await db.scalars(
                select(SearchProfile)
                .where(SearchProfile.status == "active", SearchProfile.next_run_at.is_(None))
                .limit(50)
            )
        ).all()
        for s in missing:
            user = await db.get(User, s.user_id)
            if user:
                s.next_run_at = next_search_run(s, user, now)
        await db.commit()

        users = (await db.scalars(select(User).where(User.is_active.is_(True)))).all()
        for u in users:
            slot = digest_due(u, now, window_minutes=window)
            if slot:
                await ctx["redis"].enqueue_job(
                    "digest_job", str(u.id), slot, _job_id=f"digest:{u.id}:{now:%Y%m%d}:{slot}"
                )
        # Re-queue analyses stuck in "queued" for over an hour (e.g. after a crash).
        stale = (
            await db.scalars(
                select(SearchMatch.id)
                .where(
                    SearchMatch.analysis_state == "queued",
                    SearchMatch.first_seen_at < now.replace(microsecond=0) - _hour(),
                )
                .limit(20)
            )
        ).all()
        for mid in stale:
            await ctx["redis"].enqueue_job("analyze_match_job", str(mid), _job_id=f"analyze:{mid}")


def _hour():
    from datetime import timedelta

    return timedelta(hours=1)


async def telegram_poller() -> None:
    offset = None
    backoff = 5
    while True:
        if not telegram.configured():
            await asyncio.sleep(60)
            continue
        try:
            updates = await telegram.get_updates(offset)
            backoff = 5
            for upd in updates:
                offset = upd["update_id"] + 1
                async with sessionmaker()() as db:
                    try:
                        await notify.handle_update(db, upd)
                    except Exception as e:  # never let one bad update stop the bot
                        log.warning("telegram_update_failed", error=str(e))
        except telegram.TelegramError as e:
            log.warning("telegram_poll_failed", error=str(e))
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("telegram_poll_crashed", error=type(e).__name__)
            await asyncio.sleep(backoff)


async def startup(ctx) -> None:
    setup_logging()
    try:
        await _recover(ctx)
    except Exception as e:  # recovery must never keep the worker from starting
        log.error("recovery_failed", error=type(e).__name__)
    ctx["poller"] = asyncio.create_task(telegram_poller())
    log.info("worker_started")


async def _recover(ctx) -> None:
    async with sessionmaker()() as db:
        report = await resilience.recover(db)
        if not report:
            return
        ctx["digest_window"] = resilience.digest_window(report)
        ctx["catchup_ticks"] = 2
        waiting = (
            await db.scalars(select(SearchMatch.id).where(SearchMatch.analysis_state == "queued").limit(500))
        ).all()
        for mid in waiting:
            await ctx["redis"].enqueue_job("analyze_match_job", str(mid), _job_id=f"analyze:{mid}")
        await resilience.send_report(db, report)


async def shutdown(ctx) -> None:
    with contextlib.suppress(Exception):
        async with sessionmaker()() as db:
            await resilience.heartbeat(db, clean=True)
    task = ctx.get("poller")
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class WorkerSettings:
    functions = [run_search_job, analyze_match_job, digest_job]
    cron_jobs = [cron(tick, second=0, run_at_startup=True, unique=True)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://redis:6379/0")
    max_jobs = 6
    job_timeout = 300
    max_tries = 4
    keep_result = 3600
