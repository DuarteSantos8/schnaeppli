"""Telegram Bot API client.

* Long polling (getUpdates) instead of a webhook: the app is reachable only via
  VPN, so Telegram can't call in. All traffic is outbound.
* The bot token is part of every Telegram URL. httpx logs request URLs at INFO
  level, so its logger is raised to WARNING in ``app.core.logging``; errors here
  never include the URL.
"""

from __future__ import annotations

import html
from typing import Any

import httpx

from app.core.config import get_settings

API = "https://api.telegram.org"


class TelegramError(Exception):
    pass


def esc(text: Any) -> str:
    return html.escape(str(text), quote=False)


def configured() -> bool:
    return bool(get_settings().telegram_bot_token)


async def _call(method: str, payload: dict, timeout: float = 20) -> Any:
    token = get_settings().telegram_bot_token
    if not token:
        raise TelegramError("Telegram is not configured on this server.")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{API}/bot{token}/{method}", json=payload)
    except httpx.HTTPError as e:
        raise TelegramError(f"Telegram request failed ({type(e).__name__}).") from None
    try:
        data = resp.json()
    except ValueError:
        raise TelegramError(f"Telegram returned HTTP {resp.status_code}.") from None
    if not data.get("ok"):
        raise TelegramError(f"Telegram: {str(data.get('description', 'error'))[:150]}")
    return data.get("result")


async def send_message(chat_id: str, text: str, buttons: list[list[dict]] | None = None) -> None:
    payload: dict = {
        "chat_id": chat_id,
        "text": text[:4096],
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    await _call("sendMessage", payload)


async def send_photo(
    chat_id: str, photo_url: str, caption: str, buttons: list[list[dict]] | None = None
) -> None:
    payload: dict = {"chat_id": chat_id, "photo": photo_url, "caption": caption[:1024], "parse_mode": "HTML"}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        await _call("sendPhoto", payload)
    except TelegramError:
        # Image URL refused by Telegram (hotlink protection etc.): fall back to text.
        await send_message(chat_id, caption, buttons)


async def get_updates(offset: int | None, timeout: int = 25) -> list[dict]:
    payload: dict = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    return await _call("getUpdates", payload, timeout=timeout + 10) or []


async def get_me() -> dict:
    return await _call("getMe", {})
