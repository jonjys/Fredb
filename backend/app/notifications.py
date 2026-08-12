# app/notifications.py
"""Push notifications for critical bot events, via Discord and/or Telegram
webhooks. Both are opt-in and independent of each other; whichever has
credentials configured gets used, silently skipped otherwise.

Deliberately synchronous HTTP via urllib, wrapped in asyncio.to_thread,
rather than adding aiohttp/requests as a declared dependency — it's already
a transitive dependency of ccxt, which makes it available but not something
this module should depend on directly (a ccxt version bump could drop it).
A notification is a few KB over HTTPS a few times a day at most; stdlib is
plenty and keeps requirements.txt honest about what this app actually needs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Literal

from app.config import Settings

logger = logging.getLogger("tradingbot.notifications")

Level = Literal["info", "warning", "critical"]

_DISCORD_COLOR = {"info": 0x6EA6EA, "warning": 0xD9A441, "critical": 0xE4735C}


def _post_json_sync(url: str, payload: dict, timeout: float = 10.0) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


class Notifier:
    """Fire-and-forget alerts. A broken webhook must never take down the
    trading loop that's trying to report through it — every failure is
    caught and logged here, never raised to the caller."""

    def __init__(self, settings: Settings, source: str = "bot"):
        self.settings = settings
        self.source = source  # "spot" | "futures" — tags which bot fired the alert

    @property
    def enabled(self) -> bool:
        return bool(self.settings.discord_webhook_url) or bool(
            self.settings.telegram_bot_token and self.settings.telegram_chat_id
        )

    async def send(self, title: str, message: str, level: Level = "info") -> None:
        if not self.enabled:
            return
        tasks = []
        if self.settings.discord_webhook_url:
            tasks.append(self._send_discord(title, message, level))
        if self.settings.telegram_bot_token and self.settings.telegram_chat_id:
            tasks.append(self._send_telegram(title, message, level))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Notification delivery failed: %s", result)

    async def _send_discord(self, title: str, message: str, level: Level) -> None:
        payload = {
            "embeds": [
                {
                    "title": f"[{self.source}] {title}",
                    "description": message,
                    "color": _DISCORD_COLOR[level],
                }
            ]
        }
        await asyncio.to_thread(_post_json_sync, self.settings.discord_webhook_url, payload)

    async def _send_telegram(self, title: str, message: str, level: Level) -> None:
        icon = {"info": "ℹ️", "warning": "⚠️", "critical": "\U0001f6a8"}[level]
        text = f"{icon} *[{self.source}] {title}*\n{message}"
        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        payload = {"chat_id": self.settings.telegram_chat_id, "text": text, "parse_mode": "Markdown"}
        await asyncio.to_thread(_post_json_sync, url, payload)
