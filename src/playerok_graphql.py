"""Playerok GraphQL helpers (web session cookie `token`)."""

from __future__ import annotations

from typing import Any

# Apollo persisted-query hashes used by playerok.com web.
PERSISTED = {
    "deals": "591b0e6d036c2120c8f95b97dbfdf5635df3747cd901f4895e009935229417ef",
    "items": "3f20c731f8f769a094ee3fa32e09f8e12250357e9a4f0ebb4e6988e7a0bb9260",
    "chatMessages": "9b4e264ff1b20e0fd3929afe023dee8f50affc02b85f80cb4b3dc1516ecfbaa0",
}

VIEWER_QUERY = """
query viewer {
  viewer {
    id
    username
    role
    unreadChatsCounter
    canPublishItems
    isBlocked
    balance { value }
    profile { id testimonialCounter }
  }
}
"""

CREATE_CHAT_MESSAGE = """
mutation createChatMessage($input: CreateChatMessageInput!) {
  createChatMessage(input: $input) {
    id
    text
    createdAt
    user { id username }
  }
}
"""

PAID_SALE_STATUSES = ("PAID", "PENDING")
SALE_DIRECTION = "OUT"


def edges(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    out: list[dict[str, Any]] = []
    for edge in payload.get("edges") or []:
        node = (edge or {}).get("node")
        if node:
            out.append(node)
    return out


def money(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, dict):
        return money(value.get("value") or value.get("amount"))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
