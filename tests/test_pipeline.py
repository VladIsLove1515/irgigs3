from __future__ import annotations

import pytest

from src.config import Settings
from src.db import DealStore
from src.funpay_client import FunPayClient
from src.models import DealStage, PlayerokSale
from src.pipeline import Pipeline
from src.playerok_client import PlayerokClient


def _pipe(settings: Settings) -> tuple[Pipeline, DealStore, PlayerokClient, FunPayClient]:
    store = DealStore(settings.db_path)
    playerok = PlayerokClient(settings)
    funpay = FunPayClient(settings)
    return Pipeline(settings, store, playerok, funpay), store, playerok, funpay


@pytest.mark.asyncio
async def test_dry_run_three_sales_complete(tmp_settings: Settings):
    pipe, store, playerok, funpay = _pipe(tmp_settings)
    playerok.seed_dry_sales()
    try:
        stats = await pipe.run_until_idle(max_ticks=10)
        deals = store.list_deals(20)
        assert len(deals) == 3
        assert {d.stage for d in deals} == {DealStage.COMPLETED}
        assert all(d.username and d.funpay_order_id for d in deals)
        assert stats["ingested"] >= 3
        steam = next(d for d in deals if "Steam" in d.title)
        assert steam.funpay_price == 350.0
        assert steam.username
    finally:
        await playerok.aclose()
        await funpay.aclose()


@pytest.mark.asyncio
async def test_keyword_miss_is_skipped(tmp_settings: Settings):
    pipe, store, playerok, funpay = _pipe(tmp_settings)
    playerok.seed_dry_sales(
        [
            PlayerokSale(
                id="pk-sale-skip",
                lot_id="pk-lot-other",
                title="Random CS2 sticker",
                price=100.0,
                buyer_id="b",
                chat_id="pkchat-skip",
                status="paid",
            )
        ]
    )
    try:
        await pipe.poll_once()
        assert store.list_deals() == []
    finally:
        await playerok.aclose()
        await funpay.aclose()


@pytest.mark.asyncio
async def test_thin_margin_goes_to_review(tmp_settings: Settings):
    tmp_settings.min_margin_pct = 15.0
    pipe, store, playerok, funpay = _pipe(tmp_settings)
    playerok.seed_dry_sales(
        [
            PlayerokSale(
                id="pk-sale-thin",
                lot_id="pk-lot-steam",
                title="Steam Gift Card 500 RUB",
                price=351.0,
                buyer_id="b",
                chat_id="pkchat-thin",
                status="paid",
            )
        ]
    )
    playerok._dry_chats["pkchat-thin"] = []
    try:
        await pipe.poll_once()
        deals = store.list_deals()
        assert len(deals) == 1
        assert deals[0].stage == DealStage.NEEDS_REVIEW
        assert deals[0].last_error and "margin" in deals[0].last_error
    finally:
        await playerok.aclose()
        await funpay.aclose()
