from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    dry_run: bool = True
    require_live_confirm: bool = True
    live_confirm_token: str = ""

    # Economics
    min_margin_pct: float = Field(default=15.0, ge=0)
    max_funpay_price: float = Field(default=5000.0, gt=0)
    price_slippage_pct: float = Field(default=3.0, ge=0)
    min_title_similarity: float = Field(default=0.55, ge=0.3, le=1.0)

    # Throughput / safety
    max_concurrent_deals: int = Field(default=5, ge=1, le=50)
    max_deals_per_hour: int = Field(default=20, ge=1)
    stuck_deal_minutes: int = Field(default=60, ge=5)
    welcome_cooldown_seconds: int = Field(default=120, ge=1)
    poll_interval_seconds: float = Field(default=6.0, ge=0.5)

    # Lot filter: comma-separated Playerok item/lot ids OR title keywords
    playerok_lot_ids: str = ""
    watch_keywords: str = "steam,nitro,robux,spotify"

    # Credentials
    funpay_golden_key: str = ""
    funpay_user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    playerok_token: str = ""
    playerok_ddg5: str = ""
    playerok_user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    # Optional Telegram operator alerts
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Panel
    host: str = "127.0.0.1"
    port: int = 43147
    db_path: Path = DATA_DIR / "deals.db"
    log_dir: Path = ROOT / "logs"

    @property
    def keywords(self) -> list[str]:
        return [k.strip().lower() for k in self.watch_keywords.split(",") if k.strip()]

    @property
    def lot_id_allowlist(self) -> set[str]:
        return {x.strip() for x in self.playerok_lot_ids.split(",") if x.strip()}

    def assert_live_allowed(self) -> None:
        if self.dry_run:
            raise RuntimeError("dry_run=true: live money/chat ops blocked")
        if self.require_live_confirm and self.live_confirm_token != "I_ACCEPT_LIVE_RISK":
            raise RuntimeError(
                "Set LIVE_CONFIRM_TOKEN=I_ACCEPT_LIVE_RISK "
                "(or REQUIRE_LIVE_CONFIRM=false) for live mode"
            )


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()
