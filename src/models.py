from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid4().hex


class DealStage(StrEnum):
    NEW = "new"
    AWAITING_USERNAME = "awaiting_username"
    READY = "ready"
    SOURCING = "sourcing"
    BUYING = "buying"
    BOUGHT = "bought"
    NOTIFYING = "notifying"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


ACTIVE_STAGES = {
    DealStage.NEW,
    DealStage.AWAITING_USERNAME,
    DealStage.READY,
    DealStage.SOURCING,
    DealStage.BUYING,
    DealStage.BOUGHT,
    DealStage.NOTIFYING,
}

TERMINAL_STAGES = {
    DealStage.COMPLETED,
    DealStage.FAILED,
    DealStage.NEEDS_REVIEW,
}

ALLOWED_TRANSITIONS: dict[DealStage, set[DealStage]] = {
    DealStage.NEW: {
        DealStage.AWAITING_USERNAME,
        DealStage.READY,
        DealStage.FAILED,
        DealStage.NEEDS_REVIEW,
    },
    DealStage.AWAITING_USERNAME: {
        DealStage.READY,
        DealStage.AWAITING_USERNAME,  # re-welcome / still waiting
        DealStage.FAILED,
        DealStage.NEEDS_REVIEW,
    },
    DealStage.READY: {
        DealStage.SOURCING,
        DealStage.FAILED,
        DealStage.NEEDS_REVIEW,
    },
    DealStage.SOURCING: {
        DealStage.BUYING,
        DealStage.FAILED,
        DealStage.NEEDS_REVIEW,
    },
    DealStage.BUYING: {
        DealStage.BOUGHT,
        DealStage.FAILED,
        DealStage.NEEDS_REVIEW,
    },
    DealStage.BOUGHT: {
        DealStage.NOTIFYING,
        DealStage.FAILED,
        DealStage.NEEDS_REVIEW,
    },
    DealStage.NOTIFYING: {
        DealStage.COMPLETED,
        DealStage.FAILED,
        DealStage.NEEDS_REVIEW,
    },
    DealStage.COMPLETED: set(),
    DealStage.FAILED: set(),
    DealStage.NEEDS_REVIEW: {
        DealStage.READY,
        DealStage.AWAITING_USERNAME,
        DealStage.FAILED,
    },
}


class PlayerokSale(BaseModel):
    """Inbound paid sale on Playerok (we are the seller)."""

    id: str
    lot_id: str
    title: str
    price: float
    currency: str = "RUB"
    buyer_id: str = ""
    chat_id: str = ""
    status: str = "paid"
    raw: dict[str, Any] = Field(default_factory=dict)


class FunPayLot(BaseModel):
    id: str
    title: str
    price: float
    seller_id: str = ""
    seller_username: str = ""
    url: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class FunPayOrder(BaseModel):
    id: str
    lot_id: str
    title: str
    price: float
    chat_id: str = ""
    seller_id: str = ""
    status: str = "paid"


class ChatMessage(BaseModel):
    id: str
    chat_id: str
    text: str
    from_me: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class Deal(BaseModel):
    id: str = Field(default_factory=new_id)
    stage: DealStage = DealStage.NEW
    playerok_sale_id: str
    playerok_lot_id: str
    playerok_chat_id: str = ""
    title: str
    sale_price: float
    buyer_id: str = ""
    username: str | None = None
    funpay_lot_id: str | None = None
    funpay_order_id: str | None = None
    funpay_price: float | None = None
    expected_margin_pct: float | None = None
    welcome_sent_at: datetime | None = None
    last_error: str | None = None
    dry_run: bool = True
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def touch(self) -> None:
        self.updated_at = utcnow()
