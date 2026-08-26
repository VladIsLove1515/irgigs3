from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.bot import OperatorBot
from src.config import Settings, get_settings
from src.db import DealStore
from src.funpay_client import FunPayClient
from src.models import DealStage
from src.pipeline import Pipeline
from src.playerok_client import PlayerokClient
from src.username import normalize_username

log = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = DealStore(settings.db_path)
    playerok = PlayerokClient(settings)
    funpay = FunPayClient(settings)
    operator = OperatorBot(settings)
    pipeline = Pipeline(
        settings, store, playerok, funpay, notify=operator.send
    )
    state: dict[str, Any] = {
        "settings": settings,
        "store": store,
        "pipeline": pipeline,
        "playerok": playerok,
        "funpay": funpay,
        "operator": operator,
        "last_tick": None,
        "running": True,
        "worker": None,
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.bot = state
        if settings.dry_run:
            playerok.seed_dry_sales()
        state["worker"] = asyncio.create_task(_poll_loop(state))
        store.add_event(
            f"panel up dry_run={settings.dry_run} port={settings.port}"
        )
        try:
            yield
        finally:
            state["running"] = False
            if state["worker"]:
                state["worker"].cancel()
                try:
                    await state["worker"]
                except asyncio.CancelledError:
                    pass
            await playerok.aclose()
            await funpay.aclose()
            await operator.aclose()

    app = FastAPI(title="Playerok→FunPay Bot", lifespan=lifespan)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, deal: str | None = None):
        selected = store.get(deal) if deal else None
        return TEMPLATES.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "settings": settings,
                "deals": store.list_deals(100),
                "selected": selected,
                "events": store.list_events(70),
                "last_tick": state["last_tick"],
                "health": {
                    "playerok": playerok.healthcheck(),
                    "funpay": funpay.healthcheck(),
                    "telegram": operator.enabled,
                },
            },
        )

    @app.get("/api/deals")
    async def api_deals():
        return [d.model_dump(mode="json") for d in store.list_deals(200)]

    @app.get("/api/deals/{deal_id}")
    async def api_deal(deal_id: str):
        d = store.get(deal_id)
        if not d:
            raise HTTPException(404, "not found")
        return d.model_dump(mode="json")

    @app.post("/api/tick")
    async def api_tick():
        stats = await pipeline.poll_once()
        state["last_tick"] = stats
        return stats

    @app.post("/api/deals/{deal_id}/username")
    async def api_set_username(deal_id: str, request: Request):
        form = await request.form()
        raw = str(form.get("username") or "").strip()
        d = store.get(deal_id)
        if not d:
            raise HTTPException(404, "not found")
        if not raw:
            raise HTTPException(400, "username required")
        d.username = normalize_username(raw)
        store.upsert(d)
        store.add_event(f"manual username {d.username}", deal_id=d.id)
        await pipeline.advance(d.id)
        return RedirectResponse(f"/?deal={d.id}", status_code=303)

    @app.post("/api/deals/{deal_id}/fail")
    async def api_fail(deal_id: str):
        d = store.get(deal_id)
        if not d:
            raise HTTPException(404, "not found")
        if d.stage in {DealStage.COMPLETED, DealStage.FAILED}:
            raise HTTPException(400, "already terminal")
        d.stage = DealStage.FAILED
        d.last_error = "manual fail from panel"
        store.upsert(d)
        return RedirectResponse(f"/?deal={d.id}", status_code=303)

    @app.get("/health")
    async def health():
        return {
            "ok": True,
            "dry_run": settings.dry_run,
            "active": store.count_active(),
            "last_tick": state["last_tick"],
        }

    return app


async def _poll_loop(state: dict[str, Any]) -> None:
    pipeline: Pipeline = state["pipeline"]
    settings: Settings = state["settings"]
    while state["running"]:
        try:
            stats = await pipeline.poll_once()
            state["last_tick"] = stats
            log.info("poll %s", stats)
        except Exception:
            log.exception("poll failed")
            state["store"].add_event("poll crashed", level="error")
        await asyncio.sleep(settings.poll_interval_seconds)
