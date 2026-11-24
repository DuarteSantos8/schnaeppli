"""Fixed-window rate limiting backed by Redis, with an in-memory fallback for
tests and single-process development."""

from __future__ import annotations

import time
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import get_settings


@dataclass
class Limit:
    count: int
    seconds: int


class RateLimiter:
    def __init__(self, redis: Redis | None):
        self.redis = redis
        self._mem: dict[str, tuple[int, float]] = {}

    async def hit(self, key: str, limit: Limit) -> tuple[bool, int]:
        """Register a hit. Returns (allowed, retry_after_seconds)."""
        window = int(time.time() // limit.seconds)
        bucket = f"rl:{key}:{window}"
        if self.redis is not None:
            n = await self.redis.incr(bucket)
            if n == 1:
                await self.redis.expire(bucket, limit.seconds + 1)
        else:
            n, exp = self._mem.get(bucket, (0, time.time() + limit.seconds))
            n += 1
            self._mem[bucket] = (n, exp)
            if len(self._mem) > 10_000:
                now = time.time()
                self._mem = {k: v for k, v in self._mem.items() if v[1] > now}
        retry = limit.seconds - int(time.time() % limit.seconds)
        return n <= limit.count, retry

    async def reset(self, key: str, limit: Limit) -> None:
        window = int(time.time() // limit.seconds)
        bucket = f"rl:{key}:{window}"
        if self.redis is not None:
            await self.redis.delete(bucket)
        else:
            self._mem.pop(bucket, None)


_redis: Redis | None = None
_limiter: RateLimiter | None = None


def get_redis() -> Redis | None:
    global _redis
    url = get_settings().redis_url
    if _redis is None and url and not get_settings().is_test:
        _redis = Redis.from_url(url, decode_responses=True)
    return _redis


def get_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(get_redis())
    return _limiter


def reset_limiter_for_tests() -> None:
    global _limiter
    _limiter = RateLimiter(None)


LOGIN_PER_IP = Limit(20, 15 * 60)
LOGIN_PER_ACCOUNT = Limit(8, 15 * 60)
REGISTER_PER_IP = Limit(5, 60 * 60)
API_PER_USER = Limit(600, 60)
AI_PER_USER = Limit(30, 60)
TELEGRAM_LINK = Limit(10, 60 * 60)
