from __future__ import annotations

from pathlib import Path

import pytest

from src.config import Settings


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "deals.db",
        log_dir=tmp_path / "logs",
        dry_run=True,
        poll_interval_seconds=3600,
        welcome_cooldown_seconds=1,
        watch_keywords="steam,nitro,robux,spotify",
        min_margin_pct=15.0,
        max_funpay_price=5000.0,
    )
