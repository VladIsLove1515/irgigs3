from __future__ import annotations

import logging

import httpx

from src.config import Settings

log = logging.getLogger(__name__)


class OperatorBot:
    """Optional Telegram alerts for the operator. No-op without token/chat."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = bool(settings.telegram_bot_token and settings.telegram_chat_id)
        self._client = httpx.AsyncClient(timeout=15.0) if self.enabled else None

    async def aclose(self) -> None:
        if self._client:
            await self._client.aclose()

    async def send(self, text: str) -> None:
        if not self.enabled or not self._client:
            return
        url = (
            f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        )
        try:
            resp = await self._client.post(
                url,
                json={
                    "chat_id": self.settings.telegram_chat_id,
                    "text": text[:3500],
                    "disable_web_page_preview": True,
                },
            )
            if resp.status_code >= 400:
                log.warning("telegram notify failed: %s %s", resp.status_code, resp.text)
        except Exception:
            log.exception("telegram notify error")
