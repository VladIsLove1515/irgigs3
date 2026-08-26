from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx

from src.config import Settings
from src.models import ChatMessage, PlayerokSale, utcnow
from src import playerok_graphql as gql

log = logging.getLogger(__name__)
PLAYEROK_BASE = "https://playerok.com"


def _parse_dt(value: Any):
    if not value:
        return utcnow()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return utcnow()


class PlayerokError(Exception):
    pass


class PlayerokClient:
    """Оплаты (входящие продажи) и чат Playerok."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        cookies: dict[str, str] = {}
        if settings.playerok_token:
            cookies["token"] = settings.playerok_token
        if settings.playerok_ddg5:
            cookies["__ddg5_"] = settings.playerok_ddg5
        headers = {
            "User-Agent": settings.playerok_user_agent,
            "Accept": "*/*",
            "Origin": PLAYEROK_BASE,
            "Referer": f"{PLAYEROK_BASE}/",
            "apollo-require-preflight": "true",
            "apollographql-client-name": "web",
            "Content-Type": "application/json",
        }
        if settings.playerok_token:
            headers["Authorization"] = f"Bearer {settings.playerok_token}"
        self._client = httpx.AsyncClient(
            base_url=PLAYEROK_BASE,
            timeout=25.0,
            headers=headers,
            cookies=cookies,
            follow_redirects=True,
        )
        self._dry_sales: list[PlayerokSale] | None = None
        self._dry_chats: dict[str, list[ChatMessage]] = {}
        self._seen_sale_ids: set[str] = set()
        self._viewer: dict[str, Any] | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    def healthcheck(self) -> dict[str, Any]:
        viewer = self._viewer or {}
        return {
            "platform": "playerok",
            "dry_run": self.settings.dry_run,
            "has_token": bool(self.settings.playerok_token),
            "username": viewer.get("username"),
        }

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
        self._dry_chats["pkchat-1003"] = [
            ChatMessage(
                id="m1",
                chat_id="pkchat-1003",
                text="Выдайте на @roblox_hero99 пожалуйста",
                from_me=False,
            )
        ]

    def _use_dry(self) -> bool:
        return self.settings.dry_run or not self.settings.playerok_token

    def _raise_if_blocked(self, resp: httpx.Response) -> None:
        text = resp.text[:400]
        lower = text.lower()
        if resp.status_code in {403, 429} or "ddos-guard" in lower or "just a moment" in lower:
            raise PlayerokError(
                "Playerok blocked this IP (DDoS-Guard). "
                "Run the bot from the same network as the browser where you logged in. "
                "Optional: set PLAYEROK_DDG5 to cookie __ddg5_ from that browser."
            )
        if resp.status_code >= 400:
            raise PlayerokError(f"Playerok HTTP {resp.status_code}: {text[:180]}")

    async def _gql_post(
        self, operation: str, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {
            "x-gql-op": operation,
            "x-apollo-operation-name": operation,
        }
        resp = await self._client.post(
            "/graphql",
            headers=headers,
            json={
                "operationName": operation,
                "query": query,
                "variables": variables or {},
            },
        )
        self._raise_if_blocked(resp)
        try:
            body = resp.json()
        except Exception as exc:
            raise PlayerokError(f"Playerok non-JSON: {resp.text[:180]}") from exc
        if body.get("errors"):
            raise PlayerokError(f"Playerok GraphQL: {body['errors']}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise PlayerokError("Playerok GraphQL returned empty data")
        return data

    async def _gql_persisted(
        self, operation: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        headers = {
            "x-gql-op": operation,
            "x-apollo-operation-name": operation,
        }
        params = {
            "operationName": operation,
            "variables": json.dumps(variables, ensure_ascii=False),
            "extensions": json.dumps(
                {
                    "persistedQuery": {
                        "version": 1,
                        "sha256Hash": gql.PERSISTED[operation],
                    }
                }
            ),
        }
        resp = await self._client.get("/graphql", headers=headers, params=params)
        self._raise_if_blocked(resp)
        try:
            body = resp.json()
        except Exception as exc:
            raise PlayerokError(f"Playerok non-JSON: {resp.text[:180]}") from exc
        if body.get("errors"):
            raise PlayerokError(f"Playerok GraphQL: {body['errors']}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise PlayerokError("Playerok GraphQL returned empty data")
        return data

    async def viewer(self) -> dict[str, Any]:
        if not self.settings.playerok_token:
            raise PlayerokError("PLAYEROK_TOKEN is empty")
        data = await self._gql_post("viewer", gql.VIEWER_QUERY)
        viewer = data.get("viewer")
        if not viewer:
            raise PlayerokError("token rejected (viewer is null) — log in again and copy cookie token")
        self._viewer = viewer
        return viewer

    async def list_my_items(self, *, count: int = 24) -> list[dict[str, Any]]:
        viewer = self._viewer or await self.viewer()
        data = await self._gql_persisted(
            "items",
            {
                "pagination": {"first": count, "after": None},
                "filter": {"userId": viewer["id"], "status": None},
                "showForbiddenImage": True,
            },
        )
        return gql.edges(data.get("items"))

    async def list_live_sales(self, *, count: int = 24) -> list[PlayerokSale]:
        viewer = self._viewer or await self.viewer()
        data = await self._gql_persisted(
            "deals",
            {
                "pagination": {"first": count, "after": None},
                "filter": {
                    "userId": viewer["id"],
                    "direction": gql.SALE_DIRECTION,
                    "status": list(gql.PAID_SALE_STATUSES),
                },
                "showForbiddenImage": True,
            },
        )
        sales: list[PlayerokSale] = []
        for node in gql.edges(data.get("deals")):
            sale = sale_from_deal_node(node)
            if sale:
                sales.append(sale)
        return sales

    async def snapshot(self) -> dict[str, Any]:
        """Read-only account dump for --playerok-whoami."""
        viewer = await self.viewer()
        items = await self.list_my_items()
        try:
            sales = await self.list_live_sales()
        except PlayerokError as exc:
            log.warning("deals fetch failed: %s", exc)
            sales = []
        return {
            "id": viewer.get("id"),
            "username": viewer.get("username"),
            "role": viewer.get("role"),
            "balance": gql.money((viewer.get("balance") or {}).get("value")),
            "can_publish": viewer.get("canPublishItems"),
            "blocked": viewer.get("isBlocked"),
            "items": [
                {
                    "id": it.get("id"),
                    "title": it.get("name") or it.get("slug"),
                    "price": gql.money(it.get("price") if it.get("price") is not None else it.get("rawPrice")),
                    "status": it.get("status"),
                }
                for it in items
            ],
            "paid_sales": [
                {
                    "id": s.id,
                    "title": s.title,
                    "price": s.price,
                    "status": s.status,
                    "chat_id": s.chat_id,
                }
                for s in sales
            ],
        }

    async def list_new_sales(self) -> list[PlayerokSale]:
        if self._use_dry():
            if self._dry_sales is None:
                self.seed_dry_sales()
            assert self._dry_sales is not None
            fresh = [s for s in self._dry_sales if s.id not in self._seen_sale_ids]
            for s in fresh:
                self._seen_sale_ids.add(s.id)
            return fresh
        fresh: list[PlayerokSale] = []
        for sale in await self.list_live_sales():
            if sale.id in self._seen_sale_ids:
                continue
            self._seen_sale_ids.add(sale.id)
            fresh.append(sale)
        return fresh

    async def get_chat_messages(self, chat_id: str) -> list[ChatMessage]:
        if not chat_id:
            return []
        if self._use_dry():
            return list(self._dry_chats.get(chat_id, []))
        data = await self._gql_persisted(
            "chatMessages",
            {
                "pagination": {"first": 24, "after": None},
                "filter": {"chatId": chat_id},
                "hasSupportAccess": False,
                "showForbiddenImage": True,
            },
        )
        me = (self._viewer or {}).get("id")
        out: list[ChatMessage] = []
        for node in gql.edges(data.get("chatMessages")):
            user = node.get("user") or {}
            out.append(
                ChatMessage(
                    id=str(node.get("id") or uuid4().hex[:12]),
                    chat_id=chat_id,
                    text=str(node.get("text") or ""),
                    from_me=bool(me and user.get("id") == me),
                    created_at=_parse_dt(node.get("createdAt")),
                )
            )
        return out

    async def send_message(self, chat_id: str, text: str) -> None:
        if not chat_id or not text.strip():
            raise PlayerokError("refuse empty chat_id/text")
        if self._use_dry():
            msg = ChatMessage(
                id=uuid4().hex[:12],
                chat_id=chat_id,
                text=text,
                from_me=True,
                created_at=utcnow(),
            )
            self._dry_chats.setdefault(chat_id, []).append(msg)
            log.info("DRY Playerok chat %s: %s", chat_id, text[:80])
            from src.username import extract_username_from_messages

            existing = extract_username_from_messages(
                [m.text for m in self._dry_chats[chat_id] if not m.from_me]
            )
            if existing is None and (
                "@" in text or "username" in text.lower() or "ник" in text.lower()
            ):
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
        await self._gql_post(
            "createChatMessage",
            gql.CREATE_CHAT_MESSAGE,
            {"input": {"chatId": chat_id, "text": text, "imagesIds": []}},
        )
        log.info("Playerok chat %s: %s", chat_id, text[:80])


def sale_from_deal_node(node: dict[str, Any]) -> PlayerokSale | None:
    deal_id = node.get("id")
    if not deal_id:
        return None
    item = node.get("item") or {}
    chat = node.get("chat") or {}
    user = node.get("user") or {}
    tx = node.get("transaction") or {}
    price = gql.money(
        item.get("price")
        if item.get("price") is not None
        else item.get("rawPrice")
        if item.get("rawPrice") is not None
        else tx.get("value")
    )
    status = str(node.get("status") or "paid").lower()
    return PlayerokSale(
        id=str(deal_id),
        lot_id=str(item.get("id") or ""),
        title=str(item.get("name") or item.get("slug") or "Playerok item"),
        price=price,
        buyer_id=str(user.get("id") or ""),
        chat_id=str(chat.get("id") or ""),
        status=status,
        raw=node,
    )
