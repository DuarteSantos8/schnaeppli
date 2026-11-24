"""Timezone-aware schedule computation (DST-safe via zoneinfo)."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import SearchProfile, User


def _parse(t: str) -> time:
    h, m = t.split(":")
    return time(int(h), int(m))


def next_daily(
    after: datetime, times: list[str], tz_name: str, days: list[int] | None = None
) -> datetime | None:
    """Next moment strictly after ``after`` matching one of the local ``times``
    on one of ``days`` (Monday=0)."""
    if not times:
        return None
    tz = ZoneInfo(tz_name or "Europe/Zurich")
    local = after.astimezone(tz)
    allowed = set(days) if days is not None else set(range(7))
    if not allowed:
        return None
    for offset in range(0, 8):
        day = (local + timedelta(days=offset)).date()
        if day.weekday() not in allowed:
            continue
        for t in sorted(_parse(x) for x in times):
            candidate = datetime.combine(day, t, tzinfo=tz)
            if candidate > local:
                return candidate.astimezone(UTC)
    return None


def search_times(search: SearchProfile, user: User) -> dict:
    sched = search.schedule or {"mode": "default"}
    mode = sched.get("mode", "default")
    if mode == "interval":
        return {"interval_hours": max(1, min(48, int(sched.get("hours", 6))))}
    if mode == "custom" and sched.get("times"):
        return {"times": sched["times"]}
    return {"times": (user.search_schedule or {}).get("times", ["06:30", "17:30"])}


def next_search_run(search: SearchProfile, user: User, after: datetime) -> datetime | None:
    if search.status != "active":
        return None
    spec = search_times(search, user)
    if "interval_hours" in spec:
        base = search.last_run_at or after
        nxt = base + timedelta(hours=spec["interval_hours"])
        return nxt if nxt > after else after + timedelta(minutes=1)
    return next_daily(after, spec["times"], user.timezone)


def digest_due(user: User, now: datetime, window_minutes: int = 5) -> str | None:
    """Returns the digest slot ("07:00") if one is due now, else None."""
    prefs = user.notification_prefs or {}
    if not prefs.get("digest_enabled", True):
        return None
    tz = ZoneInfo(user.timezone or "Europe/Zurich")
    local = now.astimezone(tz)
    if local.weekday() not in set(prefs.get("digest_days", range(7))):
        return None
    for t in prefs.get("digest_times", ["07:00", "18:00"]):
        slot = datetime.combine(local.date(), _parse(t), tzinfo=tz)
        if timedelta(0) <= local - slot < timedelta(minutes=window_minutes):
            last = user.last_digest_at
            if last is None or last.astimezone(tz) < slot:
                return t
    return None
