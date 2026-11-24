"""Crash recovery: outage detection, catch-up and the report."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import sessionmaker, utcnow
from app.models import Notification, SearchProfile, SearchRun, User
from app.services import resilience
from app.services.schedule import digest_due


async def test_no_outage_on_first_start_or_quick_restart(alice):
    async with sessionmaker()() as db:
        assert await resilience.recover(db) is None  # first ever start: just records a heartbeat
        now = utcnow()
        await resilience.heartbeat(db, now - timedelta(minutes=2), clean=True)
        assert await resilience.recover(db, now) is None  # a redeploy, not an outage


async def test_crash_is_detected_runs_restarted_and_admin_told(alice, monkeypatch):
    s = (await alice.post("/api/searches", json={"title": "Camera", "max_budget": 300})).json()
    sent = []

    async def fake_send(chat_id, text, buttons=None):
        sent.append(text)

    monkeypatch.setattr("app.services.telegram.send_message", fake_send)
    now = utcnow()
    async with sessionmaker()() as db:
        search = await db.get(SearchProfile, uuid.UUID(s["id"]))
        search.next_run_at = now - timedelta(hours=3)  # due while the server was down
        db.add(SearchRun(search_id=search.id, started_at=now - timedelta(hours=4), status="running"))
        await resilience.heartbeat(db, now - timedelta(hours=4))  # last sign of life, no clean mark
        await db.commit()

        report = await resilience.recover(db, now)
        assert report is not None
        assert report["minutes"] == 240 and report["clean"] is False
        assert report["searches_caught_up"] == 1
        assert report["runs_restarted"] == ["Camera"]
        run = (await db.scalars(select(SearchRun))).one()
        assert run.status == "failed" and "Interrupted" in run.error

        assert resilience.digest_window(report) == 245
        text = resilience.report_text(report)
        assert "offline" in text and "crashed" in text and "4 h" in text

        await resilience.send_report(db, report)
        alice_id = (await db.scalars(select(User.id))).first()
        note = (await db.scalars(select(Notification).where(Notification.user_id == alice_id))).one()
        assert note.kind == "outage_report"

    dash = (await alice.get("/api/dashboard")).json()
    assert dash["last_outage"]["minutes"] == 240


async def test_clean_long_restart_is_reported_as_planned(alice):
    now = utcnow()
    async with sessionmaker()() as db:
        await resilience.heartbeat(db, now - timedelta(minutes=30), clean=True)
        report = await resilience.recover(db, now)
        assert report and report["clean"] is True
        assert "shut down normally" in resilience.report_text(report)


async def test_outage_dashboard_is_admin_only(alice, bob):
    now = utcnow()
    async with sessionmaker()() as db:
        await resilience.heartbeat(db, now - timedelta(hours=1))
        await resilience.recover(db, now)
    assert (await alice.get("/api/dashboard")).json()["last_outage"] is not None
    assert (await bob.get("/api/dashboard")).json()["last_outage"] is None


def _user(times, last=None):
    return User(
        email="x@example.com",
        display_name="x",
        password_hash="x",
        timezone="Europe/Zurich",
        notification_prefs={"digest_enabled": True, "digest_times": times, "digest_days": list(range(7))},
        last_digest_at=last,
    )


def test_digest_normally_only_on_time():
    # 07:00 Zurich = 06:00 UTC in winter
    u = _user(["07:00", "18:00"])
    assert digest_due(u, datetime(2026, 11, 24, 6, 2, tzinfo=UTC)) == "07:00"
    assert digest_due(u, datetime(2026, 11, 24, 8, 0, tzinfo=UTC)) is None


def test_missed_digest_is_sent_late_once_newest_slot():
    last = datetime(2026, 11, 23, 17, 0, tzinfo=UTC)  # yesterday 18:00 sent
    u = _user(["07:00", "12:00"], last)
    now = datetime(2026, 11, 24, 12, 30, tzinfo=UTC)  # 13:30 local, both slots missed
    assert digest_due(u, now) is None
    assert digest_due(u, now, window_minutes=8 * 60) == "12:00"  # the newest missed slot
    u.last_digest_at = now
    assert digest_due(u, now, window_minutes=8 * 60) is None  # one digest covers both


def test_missed_digest_across_midnight():
    u = _user(["22:00"], datetime(2026, 11, 22, 21, 0, tzinfo=UTC))
    now = datetime(2026, 11, 24, 0, 30, tzinfo=UTC)  # 01:30 local, yesterday's 22:00 missed
    assert digest_due(u, now, window_minutes=6 * 60) == "22:00"
