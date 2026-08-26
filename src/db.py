from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from src.models import ACTIVE_STAGES, Deal, DealStage, utcnow

log = logging.getLogger(__name__)
_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def _dt(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value)


class DealStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS deals (
                    id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    playerok_sale_id TEXT NOT NULL UNIQUE,
                    playerok_lot_id TEXT NOT NULL,
                    playerok_chat_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    sale_price REAL NOT NULL,
                    buyer_id TEXT NOT NULL DEFAULT '',
                    username TEXT,
                    funpay_lot_id TEXT,
                    funpay_order_id TEXT,
                    funpay_price REAL,
                    expected_margin_pct REAL,
                    welcome_sent_at TEXT,
                    last_error TEXT,
                    dry_run INTEGER NOT NULL DEFAULT 1,
                    meta TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_deals_stage ON deals(stage);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deal_id TEXT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _row(self, row: sqlite3.Row) -> Deal:
        return Deal(
            id=row["id"],
            stage=DealStage(row["stage"]),
            playerok_sale_id=row["playerok_sale_id"],
            playerok_lot_id=row["playerok_lot_id"],
            playerok_chat_id=row["playerok_chat_id"] or "",
            title=row["title"],
            sale_price=row["sale_price"],
            buyer_id=row["buyer_id"] or "",
            username=row["username"],
            funpay_lot_id=row["funpay_lot_id"],
            funpay_order_id=row["funpay_order_id"],
            funpay_price=row["funpay_price"],
            expected_margin_pct=row["expected_margin_pct"],
            welcome_sent_at=_dt(row["welcome_sent_at"]),
            last_error=row["last_error"],
            dry_run=bool(row["dry_run"]),
            meta=json.loads(row["meta"] or "{}"),
            created_at=_dt(row["created_at"]) or utcnow(),
            updated_at=_dt(row["updated_at"]) or utcnow(),
        )

    def upsert(self, deal: Deal) -> Deal:
        deal.touch()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO deals (
                    id, stage, playerok_sale_id, playerok_lot_id, playerok_chat_id,
                    title, sale_price, buyer_id, username, funpay_lot_id,
                    funpay_order_id, funpay_price, expected_margin_pct,
                    welcome_sent_at, last_error, dry_run, meta, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    stage=excluded.stage,
                    playerok_chat_id=excluded.playerok_chat_id,
                    username=excluded.username,
                    funpay_lot_id=excluded.funpay_lot_id,
                    funpay_order_id=excluded.funpay_order_id,
                    funpay_price=excluded.funpay_price,
                    expected_margin_pct=excluded.expected_margin_pct,
                    welcome_sent_at=excluded.welcome_sent_at,
                    last_error=excluded.last_error,
                    meta=excluded.meta,
                    updated_at=excluded.updated_at
                """,
                (
                    deal.id,
                    deal.stage.value,
                    deal.playerok_sale_id,
                    deal.playerok_lot_id,
                    deal.playerok_chat_id,
                    deal.title,
                    deal.sale_price,
                    deal.buyer_id,
                    deal.username,
                    deal.funpay_lot_id,
                    deal.funpay_order_id,
                    deal.funpay_price,
                    deal.expected_margin_pct,
                    deal.welcome_sent_at.isoformat() if deal.welcome_sent_at else None,
                    deal.last_error,
                    1 if deal.dry_run else 0,
                    json.dumps(deal.meta, ensure_ascii=False),
                    deal.created_at.isoformat(),
                    deal.updated_at.isoformat(),
                ),
            )
        return deal

    def get(self, deal_id: str) -> Deal | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM deals WHERE id = ?", (deal_id,)
            ).fetchone()
        return self._row(row) if row else None

    def by_sale(self, sale_id: str) -> Deal | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM deals WHERE playerok_sale_id = ?", (sale_id,)
            ).fetchone()
        return self._row(row) if row else None

    def list_deals(self, limit: int = 100) -> list[Deal]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM deals ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def list_by_stages(self, stages: set[DealStage]) -> list[Deal]:
        if not stages:
            return []
        qs = ",".join("?" for _ in stages)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM deals WHERE stage IN ({qs}) ORDER BY updated_at ASC",
                tuple(s.value for s in stages),
            ).fetchall()
        return [self._row(r) for r in rows]

    def count_active(self) -> int:
        return len(self.list_by_stages(ACTIVE_STAGES))

    def count_created_since(self, since: datetime) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM deals WHERE created_at >= ?",
                (since.isoformat(),),
            ).fetchone()
        return int(row["c"])

    def add_event(
        self, message: str, *, deal_id: str | None = None, level: str = "info"
    ) -> None:
        log.log(
            _LEVELS.get(level, logging.INFO),
            "%s%s",
            message,
            f" deal={deal_id[:8]}" if deal_id else "",
        )
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events(deal_id, level, message, created_at) VALUES (?,?,?,?)",
                (deal_id, level, message, utcnow().isoformat()),
            )

    def list_events(self, limit: int = 80) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, deal_id, level, message, created_at
                FROM events ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_stuck(self, older_than_minutes: int) -> list[Deal]:
        """Awaiting username is allowed to wait; other active stages are not."""
        cutoff = utcnow() - timedelta(minutes=older_than_minutes)
        stuck: list[Deal] = []
        watch = ACTIVE_STAGES - {DealStage.AWAITING_USERNAME}
        for deal in self.list_by_stages(watch):
            if deal.updated_at < cutoff:
                prev = deal.stage
                deal.stage = DealStage.NEEDS_REVIEW
                deal.last_error = f"stuck in {prev.value} > {older_than_minutes}m"
                self.upsert(deal)
                self.add_event(
                    f"needs_review: stuck in {prev.value}",
                    deal_id=deal.id,
                    level="warn",
                )
                stuck.append(deal)
        return stuck
