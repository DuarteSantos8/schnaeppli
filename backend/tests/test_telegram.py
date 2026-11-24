"""Telegram linking via one-time code, without calling Telegram."""

from sqlalchemy import select

from app.core.db import sessionmaker
from app.models import TelegramLink, User
from app.services import notify, telegram


async def test_link_with_code_and_stop(alice, monkeypatch):
    sent = []

    async def fake_send(chat_id, text, buttons=None):
        sent.append((chat_id, text))

    monkeypatch.setattr(telegram, "send_message", fake_send)
    async with sessionmaker()() as db:
        user = await db.scalar(select(User))
        code = await notify.create_link_code(db, user)
        # wrong code
        await notify.handle_update(
            db, {"message": {"chat": {"id": 42, "type": "private"}, "text": "/start WRONG123"}}
        )
        link = await db.scalar(select(TelegramLink))
        assert link.chat_id is None
        # group chats are ignored
        await notify.handle_update(
            db, {"message": {"chat": {"id": 7, "type": "group"}, "text": f"/start {code}"}}
        )
        assert (await db.scalar(select(TelegramLink))).chat_id is None
        # right code
        await notify.handle_update(
            db,
            {
                "message": {
                    "chat": {"id": 42, "type": "private"},
                    "from": {"username": "al"},
                    "text": f"/start {code}",
                }
            },
        )
        link = await db.scalar(select(TelegramLink))
        await db.refresh(link)
        assert link.chat_id == "42" and link.code_hash is None
        # code is single use
        await notify.handle_update(
            db, {"message": {"chat": {"id": 99, "type": "private"}, "text": f"/start {code}"}}
        )
        await db.refresh(link)
        assert link.chat_id == "42"
        await notify.handle_update(db, {"message": {"chat": {"id": 42, "type": "private"}, "text": "/stop"}})
        await db.refresh(link)
        assert link.chat_id is None
    assert any("Connected" in t for _, t in sent)
