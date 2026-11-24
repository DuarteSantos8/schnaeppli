"""Enqueue background jobs (arq). In tests / without Redis, jobs are recorded
instead so they can be run explicitly."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings

_pool = None
recorded: list[tuple[str, tuple]] = []


async def _get_pool():
    global _pool
    if _pool is None:
        from arq import create_pool
        from arq.connections import RedisSettings

        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def enqueue(name: str, *args: Any, job_id: str | None = None) -> None:
    s = get_settings()
    if s.is_test or not s.redis_url:
        recorded.append((name, args))
        return
    pool = await _get_pool()
    await pool.enqueue_job(name, *[str(a) for a in args], _job_id=job_id)
