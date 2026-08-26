from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import httpx

from src.config import Settings
from src.models import ChatMessage, PlayerokSale, utcnow

log = logging.getLogger(__name__)
PLAYEROK_BASE = "https://playerok.com"


class PlayerokError(Exception):
    pass


class PlayerokClient:
    """Оплаты (входящие продажи) и чат Playerok."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        headers = {"User-Agent": settings.playerok_user_agent}
        if settings.playerok_token:
            headers["Authorization"] = f"Bearer {settings.playerok_token}"
        self._client = httpx.AsyncClient(
            base_url=PLAYEROK_BASE,
            timeout=25.0,
            headers=headers,
            follow_redirects=True,
        )
        self._dry_sales: list[PlayerokSale] | None = None
        self._dry_chats: dict[str, list[ChatMessage]] = {}
        self._seen_sale_ids: set[str] = set()

    async def aclose(self) -> None:
        await self._client.aclose()

    def seed_dry_sales(self, sales: list[PlayerokSale] | None = None) -> None:
        """Install / replace dry-run inbound sales (also used by tests)."""
        if sales is not None:
            self._dry_sales = sales
            return
        self._dry_sales = [
            PlayerokSale(
                id="pk-sale-1001",
                lot_id="pk-lot-steam",
                title="Steam Gift Card 500 RUB",
                price=450.0,
                buyer_id="buyer-1",
                chat_id="pkchat-1001",
                status="paid",
            ),
            PlayerokSale(
                id="pk-sale-1002",
                lot_id="pk-lot-nitro",
                title="Discord Nitro 1 Month",
                price=320.0,
                buyer_id="buyer-2",
                chat_id="pkchat-1002",
                status="paid",
            ),
            # Buyer already dropped username in chat history
            PlayerokSale(
                id="pk-sale-1003",
                lot_id="pk-lot-robux",
                title="Roblox Robux 800",
                price=290.0,
                buyer_id="buyer-3",
                chat_id="pkchat-1003",
                status="paid",
            ),
        ]
        # Preload chat for sale 1003 with username; others empty until welcome.
        self._dry_chats["pkchat-1003"] = [
            ChatMessage(
                id="m1",
                chat_id="pkchat-1003",
                text="Выдайте на @roblox_hero99 пожалуйста",
                from_me=False,
            )
        ]

    async def list_new_sales(self) -> list[PlayerokSale]:
        if self.settings.dry_run or not self.settings.playerok_token:
            if self._dry_sales is None:
                self.seed_dry_sales()
            assert self._dry_sales is not None
            fresh = [s for s in self._dry_sales if s.id not in self._seen_sale_ids]
            for s in fresh:
                self._seen_sale_ids.add(s.id)
            return fresh
        raise PlayerokError(
            "Live Playerok sales polling gated until token + API verified"
        )

    async def get_chat_messages(self, chat_id: str) -> list[ChatMessage]:
        if not chat_id:
            return []
        if self.settings.dry_run or not self.settings.playerok_token:
            return list(self._dry_chats.get(chat_id, []))
        raise PlayerokError("Live Playerok chat read gated")

    async def send_message(self, chat_id: str, text: str) -> None:
        if not chat_id or not text.strip():
            raise PlayerokError("refuse empty chat_id/text")
        if self.settings.dry_run or not self.settings.playerok_token:
            msg = ChatMessage(
                id=uuid4().hex[:12],
                chat_id=chat_id,
                text=text,
                from_me=True,
                created_at=utcnow(),
            )
            self._dry_chats.setdefault(chat_id, []).append(msg)
            log.info("DRY Playerok chat %s: %s", chat_id, text[:80])
            # Simulate buyer reply with username shortly after WELCOME in dry-run,
            # unless a username is already present.
            from src.username import extract_username_from_messages

            existing = extract_username_from_messages(
                [m.text for m in self._dry_chats[chat_id] if not m.from_me]
            )
            if existing is None and ("@" in text or "username" in text.lower() or "ник" in text.lower()):
                # Synthetic buyer reply for dry-run (underscores only — valid @handle).
                handle = "user_" + chat_id.replace("pkchat-", "").replace("-", "_")
                reply = ChatMessage(
                    id=uuid4().hex[:12],
                    chat_id=chat_id,
                    text=f"@{handle}",
                    from_me=False,
                    created_at=utcnow(),
                )
                self._dry_chats[chat_id].append(reply)
            return
        self.settings.assert_live_allowed()
        raise PlayerokError("Live Playerok chat send gated")

    def healthcheck(self) -> dict[str, Any]:
        return {
            "platform": "playerok",
            "dry_run": self.settings.dry_run,
            "has_token": bool(self.settings.playerok_token),
        }
