from __future__ import annotations

from fastapi.testclient import TestClient

from src.config import Settings
from src.models import Deal, DealStage
from src.web import create_app


def test_health_tick_and_panel(tmp_settings: Settings):
    app = create_app(tmp_settings)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["ok"] is True
        assert body["dry_run"] is True

        tick = client.post("/api/tick")
        assert tick.status_code == 200
        stats = tick.json()
        assert "ingested" in stats

        page = client.get("/")
        assert page.status_code == 200
        assert "Playerok" in page.text
        assert "DRY_RUN" in page.text

        deals = client.get("/api/deals")
        assert deals.status_code == 200
        rows = deals.json()
        assert len(rows) == 3
        assert {row["stage"] for row in rows} == {"completed"}


def test_manual_fail_and_username(tmp_settings: Settings):
    app = create_app(tmp_settings)
    with TestClient(app) as client:
        store = app.state.bot["store"]
        deal = Deal(
            stage=DealStage.AWAITING_USERNAME,
            playerok_sale_id="manual-1",
            playerok_lot_id="pk-lot-steam",
            playerok_chat_id="pkchat-manual",
            title="Steam Gift Card 500 RUB",
            sale_price=450.0,
            dry_run=True,
        )
        store.upsert(deal)

        fail = client.post(f"/api/deals/{deal.id}/fail", follow_redirects=False)
        assert fail.status_code == 303
        assert store.get(deal.id).stage == DealStage.FAILED

        other = Deal(
            stage=DealStage.AWAITING_USERNAME,
            playerok_sale_id="manual-2",
            playerok_lot_id="pk-lot-nitro",
            playerok_chat_id="pkchat-manual-2",
            title="Discord Nitro 1 Month",
            sale_price=320.0,
            dry_run=True,
        )
        store.upsert(other)
        set_user = client.post(
            f"/api/deals/{other.id}/username",
            data={"username": "nitro_buyer_1"},
            follow_redirects=False,
        )
        assert set_user.status_code == 303
        refreshed = store.get(other.id)
        assert refreshed.username == "@nitro_buyer_1"
        assert refreshed.stage == DealStage.COMPLETED
