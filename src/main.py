from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import uvicorn

from src.config import Settings, get_settings
from src.db import DealStore
from src.funpay_client import FunPayClient
from src.pipeline import Pipeline
from src.playerok_client import PlayerokClient
from src.web import create_app


def setup_logging(settings: Settings) -> None:
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)
    log_path = log_dir / "bot.log"
    already = any(
        getattr(h, "baseFilename", None) == str(log_path.resolve())
        for h in root.handlers
    )
    if not already:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Playerok sale → FunPay fulfill bot"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run dry-run poll until idle, print deals, exit",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_logging(settings)

    if args.once:
        asyncio.run(_run_once(settings))
        return

    app = create_app(settings)
    host = args.host or settings.host
    port = args.port or settings.port
    print(f"Panel: http://{host}:{port}  dry_run={settings.dry_run}")
    uvicorn.run(app, host=host, port=port, log_level="info")


async def _run_once(settings) -> None:
    settings.welcome_cooldown_seconds = 1
    store = DealStore(settings.db_path)
    playerok = PlayerokClient(settings)
    funpay = FunPayClient(settings)
    playerok.seed_dry_sales()
    pipe = Pipeline(settings, store, playerok, funpay)
    try:
        stats = await pipe.run_until_idle(max_ticks=25)
        print(f"done: {stats}")
        for d in store.list_deals(20):
            print(
                f"  {d.id[:8]} {d.stage.value:20} "
                f"user={d.username or '-':16} "
                f"sale={d.sale_price} buy={d.funpay_price} "
                f"{d.title[:32]}"
            )
    finally:
        await playerok.aclose()
        await funpay.aclose()


if __name__ == "__main__":
    main(sys.argv[1:])
