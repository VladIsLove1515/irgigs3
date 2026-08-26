from __future__ import annotations

import hashlib
import logging
from typing import Any
from uuid import uuid4

import httpx

from src.config import Settings
from src.models import ChatMessage, FunPayLot, FunPayOrder, utcnow

log = logging.getLogger(__name__)
FUNPAY_BASE = "https://funpay.com"


class FunPayError(Exception):
    pass


class FunPayClient:
    """FunPay витрина / покупка / сообщение продавцу."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=FUNPAY_BASE,
            timeout=25.0,
            headers={"User-Agent": settings.funpay_user_agent},
            cookies=(
                {"golden_key": settings.funpay_golden_key}
                if settings.funpay_golden_key
                else {}
            ),
            follow_redirects=True,
        )
        # dry-run chat log: chat_id → messages
        self._dry_chats: dict[str, list[ChatMessage]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    def _mock_catalog(self) -> list[FunPayLot]:
        samples = [
            ("fp-steam-500", "Steam Gift Card 500 RUB", 350.0, "seller-a"),
            ("fp-nitro-1m", "Discord Nitro 1 Month", 240.0, "seller-b"),
            ("fp-robux-800", "Roblox Robux 800", 210.0, "seller-c"),
            ("fp-noise", "Random CS2 sticker", 40.0, "seller-d"),
        ]
        return [
            FunPayLot(
                id=eid,
                title=title,
                price=price,
                seller_id=seller,
                seller_username=seller,
                url=f"{FUNPAY_BASE}/lots/{eid}/",
                raw={"mock": True},
            )
            for eid, title, price, seller in samples
        ]

    async def search_lots(self, query: str, *, limit: int = 15) -> list[FunPayLot]:
        if self.settings.dry_run or not self.settings.funpay_golden_key:
            lots = self._mock_catalog()
            q = query.lower()
            tokens = [t for t in q.replace("-", " ").split() if len(t) > 2]
            scored: list[tuple[float, FunPayLot]] = []
            for lot in lots:
                lt = lot.title.lower()
                hits = sum(1 for t in tokens if t in lt)
                if hits:
                    scored.append((hits / max(len(tokens), 1), lot))
            scored.sort(key=lambda x: (-x[0], x[1].price))
            return [lot for _, lot in scored[:limit]]
        raise FunPayError(
            "Live FunPay search gated until golden_key + parser verified"
        )

    async def get_lot(self, lot_id: str) -> FunPayLot | None:
        if not lot_id:
            return None
        if self.settings.dry_run or not self.settings.funpay_golden_key:
            for lot in self._mock_catalog():
                if lot.id == lot_id:
                    return lot
            return None
        raise FunPayError(
            "Live FunPay lot fetch gated until golden_key + parser verified"
        )

    async def get_balance(self) -> float:
        if self.settings.dry_run or not self.settings.funpay_golden_key:
            return 25_000.0
        raise FunPayError("Live FunPay balance requires verified session")

    async def buy_lot(self, lot: FunPayLot, *, max_price: float) -> FunPayOrder:
        if lot.price > max_price:
            raise FunPayError(f"refuse buy {lot.price} > max {max_price}")
        if self.settings.dry_run:
            order_id = "fpord-" + hashlib.sha1(lot.id.encode()).hexdigest()[:10]
            chat_id = f"fpchat-{lot.seller_id}-{order_id[-6:]}"
            self._dry_chats.setdefault(chat_id, [])
            log.info("DRY FunPay buy %s @ %s → %s", lot.id, lot.price, order_id)
            return FunPayOrder(
                id=order_id,
                lot_id=lot.id,
                title=lot.title,
                price=lot.price,
                chat_id=chat_id,
                seller_id=lot.seller_id,
                status="paid",
            )
        self.settings.assert_live_allowed()
        raise FunPayError("Live FunPay buy gated; enable after manual QA")

    async def send_message(self, chat_id: str, text: str) -> None:
        if not chat_id or not text.strip():
            raise FunPayError("refuse empty chat_id/text")
        if self.settings.dry_run:
            msg = ChatMessage(
                id=uuid4().hex[:12],
                chat_id=chat_id,
                text=text,
                from_me=True,
                created_at=utcnow(),
            )
            self._dry_chats.setdefault(chat_id, []).append(msg)
            log.info("DRY FunPay chat %s: %s", chat_id, text[:80])
            return
        self.settings.assert_live_allowed()
        raise FunPayError("Live FunPay chat gated; enable after manual QA")

    def healthcheck(self) -> dict[str, Any]:
        return {
            "platform": "funpay",
            "dry_run": self.settings.dry_run,
            "has_token": bool(self.settings.funpay_golden_key),
        }
