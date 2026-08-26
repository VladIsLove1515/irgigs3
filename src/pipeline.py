from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import timedelta

from src import copy
from src.config import Settings
from src.db import DealStore
from src.funpay_client import FunPayClient
from src.guards import (
    GuardError,
    assert_margin,
    assert_no_slippage,
    assert_price_positive,
    assert_title_match,
    assert_transition,
    assert_within_max_buy,
    sale_matches_filter,
)
from src.models import (
    ACTIVE_STAGES,
    Deal,
    DealStage,
    PlayerokSale,
    utcnow,
)
from src.playerok_client import PlayerokClient
from src.username import extract_username_from_messages, normalize_username

log = logging.getLogger(__name__)


class Pipeline:
    """Playerok sale → await @username → FunPay buy → tell seller username."""

    def __init__(
        self,
        settings: Settings,
        store: DealStore,
        playerok: PlayerokClient,
        funpay: FunPayClient,
        *,
        notify=None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.playerok = playerok
        self.funpay = funpay
        self.notify = notify  # optional async callable(str)
        self._lock = asyncio.Lock()

    async def _alert(self, message: str) -> None:
        self.store.add_event(message)
        if self.notify:
            try:
                await self.notify(message)
            except Exception:
                log.exception("operator notify failed")

    def _advance_stage(
        self, deal: Deal, nxt: DealStage, *, error: str | None = None
    ) -> Deal:
        if deal.stage != nxt:
            assert_transition(deal.stage, nxt)
        deal.stage = nxt
        deal.last_error = error
        self.store.upsert(deal)
        level = "error" if nxt in {DealStage.FAILED, DealStage.NEEDS_REVIEW} else "info"
        self.store.add_event(
            f"deal={deal.id[:8]} → {nxt.value}"
            + (f" err={error}" if error else ""),
            deal_id=deal.id,
            level=level,
        )
        return deal

    async def _fail(self, deal: Deal, err: Exception | str) -> Deal:
        msg = str(err)
        log.warning("deal %s fail: %s", deal.id[:8], msg)
        await self._alert(copy.OPERATOR_FAIL.format(deal_id=deal.id[:8], error=msg))
        try:
            return self._advance_stage(deal, DealStage.FAILED, error=msg)
        except GuardError:
            deal.stage = DealStage.FAILED
            deal.last_error = msg
            self.store.upsert(deal)
            return deal

    async def _review(self, deal: Deal, err: Exception | str) -> Deal:
        msg = str(err)
        try:
            return self._advance_stage(deal, DealStage.NEEDS_REVIEW, error=msg)
        except GuardError:
            deal.stage = DealStage.NEEDS_REVIEW
            deal.last_error = msg
            self.store.upsert(deal)
            return deal

    # ------------------------------------------------------------------ ingest
    async def ingest_sale(self, sale: PlayerokSale) -> Deal | None:
        """Filter lot, create deal row, kick advance()."""
        if sale.status not in {"paid", "paid_out", "completed", "pending"}:
            self.store.add_event(
                f"skip sale {sale.id}: status={sale.status}", level="debug"
            )
            return None

        reason = sale_matches_filter(
            lot_id=sale.lot_id,
            title=sale.title,
            allowlist=self.settings.lot_id_allowlist,
            keywords=self.settings.keywords,
        )
        if reason is None:
            self.store.add_event(
                f"skip sale {sale.id}: filter miss ({sale.title!r})",
                level="debug",
            )
            return None

        try:
            assert_price_positive(sale.price, "playerok sale")
        except GuardError as exc:
            self.store.add_event(f"skip sale {sale.id}: {exc}", level="warn")
            return None

        existing = self.store.by_sale(sale.id)
        if existing:
            return await self.advance(existing.id)

        if self.store.count_active() >= self.settings.max_concurrent_deals:
            self.store.add_event("skip ingest: max_concurrent_deals", level="warn")
            return None

        since = utcnow() - timedelta(hours=1)
        if self.store.count_created_since(since) >= self.settings.max_deals_per_hour:
            self.store.add_event("skip ingest: hourly cap", level="warn")
            return None

        if not sale.chat_id:
            self.store.add_event(
                f"skip sale {sale.id}: missing chat_id", level="warn"
            )
            return None

        deal = Deal(
            stage=DealStage.NEW,
            playerok_sale_id=sale.id,
            playerok_lot_id=sale.lot_id,
            playerok_chat_id=sale.chat_id,
            title=sale.title,
            sale_price=sale.price,
            buyer_id=sale.buyer_id,
            dry_run=self.settings.dry_run,
            meta={"filter": reason, "sale": sale.model_dump(mode="json")},
        )
        try:
            self.store.upsert(deal)
        except sqlite3.IntegrityError:
            existing = self.store.by_sale(sale.id)
            if existing:
                return await self.advance(existing.id)
            raise
        await self._alert(
            copy.OPERATOR_NEW_SALE.format(
                sale_id=sale.id, title=sale.title, price=sale.price
            )
        )
        return await self.advance(deal.id)

    # ------------------------------------------------------------------ advance
    async def advance(self, deal_id: str) -> Deal | None:
        """
        If chat has no @username → send WELCOME (once / cooldown) and wait.
        If username present → _source_and_buy.
        """
        deal = self.store.get(deal_id)
        if deal is None:
            return None
        if deal.stage in {DealStage.COMPLETED, DealStage.FAILED}:
            return deal
        if deal.stage in {
            DealStage.SOURCING,
            DealStage.BUYING,
            DealStage.BOUGHT,
            DealStage.NOTIFYING,
            DealStage.READY,
        }:
            return await self._source_and_buy(deal.id)

        try:
            messages = await self.playerok.get_chat_messages(deal.playerok_chat_id)
            texts = [m.text for m in messages if not m.from_me]
            # Also allow username in our stored field (manual panel override).
            username = deal.username or extract_username_from_messages(texts)
            if username:
                deal.username = normalize_username(username)
                self.store.upsert(deal)
                if deal.stage in {DealStage.NEW, DealStage.AWAITING_USERNAME}:
                    self._advance_stage(deal, DealStage.READY)
                elif deal.stage == DealStage.NEEDS_REVIEW:
                    self._advance_stage(deal, DealStage.READY)
                return await self._source_and_buy(deal.id)

            # No username yet → WELCOME
            now = utcnow()
            should_welcome = True
            if deal.welcome_sent_at is not None:
                age = (now - deal.welcome_sent_at).total_seconds()
                if age < self.settings.welcome_cooldown_seconds:
                    should_welcome = False

            if should_welcome:
                if not self.settings.dry_run:
                    self.settings.assert_live_allowed()
                await self.playerok.send_message(
                    deal.playerok_chat_id, copy.WELCOME
                )
                deal.welcome_sent_at = now
                deal.meta["welcome_count"] = int(deal.meta.get("welcome_count") or 0) + 1
                self.store.upsert(deal)
                await self._alert(
                    copy.OPERATOR_NEED_USERNAME.format(deal_id=deal.id[:8])
                )
                # Re-read chat: dry-run (and some UIs) may already contain @username.
                messages = await self.playerok.get_chat_messages(deal.playerok_chat_id)
                texts = [m.text for m in messages if not m.from_me]
                username = extract_username_from_messages(texts)
                if username:
                    deal.username = normalize_username(username)
                    if deal.stage == DealStage.NEW:
                        self._advance_stage(deal, DealStage.AWAITING_USERNAME)
                    self._advance_stage(deal, DealStage.READY)
                    return await self._source_and_buy(deal.id)

            if deal.stage == DealStage.NEW:
                return self._advance_stage(deal, DealStage.AWAITING_USERNAME)
            # Already waiting — avoid spamming stage events every poll.
            self.store.upsert(deal)
            return deal
        except (GuardError, Exception) as exc:
            return await self._fail(deal, exc)

    # ----------------------------------------------------------- source & buy
    async def _source_and_buy(self, deal_id: str) -> Deal | None:
        """Find FunPay lot → price/margin guards → buy → send username to seller."""
        deal = self.store.get(deal_id)
        if deal is None:
            return None
        if not deal.username:
            return await self._review(deal, "source_and_buy without username")

        try:
            # Idempotent resume paths
            if deal.stage == DealStage.NOTIFYING and deal.funpay_order_id:
                return await self._notify_seller(deal)
            if deal.stage == DealStage.BOUGHT and deal.funpay_order_id:
                return await self._notify_seller(deal)
            if deal.funpay_order_id and deal.meta.get("seller_notified"):
                return self._advance_stage(deal, DealStage.COMPLETED)

            if deal.stage == DealStage.NEEDS_REVIEW:
                self._advance_stage(deal, DealStage.READY)
            if deal.stage in {DealStage.NEW, DealStage.AWAITING_USERNAME}:
                self._advance_stage(deal, DealStage.READY)
            if deal.stage == DealStage.READY:
                self._advance_stage(deal, DealStage.SOURCING)

            # Confirm username to buyer once
            if not deal.meta.get("username_confirm_sent"):
                await self.playerok.send_message(
                    deal.playerok_chat_id,
                    copy.USERNAME_CONFIRM.format(username=deal.username),
                )
                deal.meta["username_confirm_sent"] = True
                self.store.upsert(deal)

            # --- choose FunPay lot ---
            if not deal.funpay_lot_id:
                candidates = await self.funpay.search_lots(deal.title, limit=10)
                if not candidates:
                    raise GuardError(f"no FunPay lots for {deal.title!r}")

                chosen = None
                last_err: Exception | None = None
                for lot in candidates:
                    try:
                        assert_title_match(
                            deal.title, lot.title, self.settings.min_title_similarity
                        )
                        assert_within_max_buy(lot.price, self.settings.max_funpay_price)
                        margin = assert_margin(
                            lot.price, deal.sale_price, self.settings.min_margin_pct
                        )
                        chosen = lot
                        deal.expected_margin_pct = margin
                        deal.funpay_lot_id = lot.id
                        deal.funpay_price = lot.price
                        deal.meta["funpay_candidate"] = lot.model_dump(mode="json")
                        break
                    except GuardError as exc:
                        last_err = exc
                        continue
                if chosen is None:
                    raise GuardError(
                        f"no profitable FunPay match: {last_err}"
                    )
                self.store.upsert(deal)

            # --- re-fetch + buy ---
            if deal.stage == DealStage.SOURCING:
                self._advance_stage(deal, DealStage.BUYING)

            live = await self.funpay.get_lot(deal.funpay_lot_id or "")
            if live is None:
                raise GuardError("FunPay lot disappeared before buy")
            assert_no_slippage(
                deal.funpay_price or live.price,
                live.price,
                self.settings.price_slippage_pct,
            )
            assert_within_max_buy(live.price, self.settings.max_funpay_price)
            assert_margin(live.price, deal.sale_price, self.settings.min_margin_pct)

            balance = await self.funpay.get_balance()
            if balance < live.price:
                raise GuardError(f"FunPay balance {balance} < {live.price}")

            if not deal.funpay_order_id:
                if not self.settings.dry_run:
                    self.settings.assert_live_allowed()
                order = await self.funpay.buy_lot(
                    live, max_price=self.settings.max_funpay_price
                )
                if not order.id or not order.chat_id:
                    raise GuardError("buy returned empty order/chat")
                deal.funpay_order_id = order.id
                deal.funpay_price = order.price
                deal.meta["funpay_order"] = order.model_dump(mode="json")
                deal.meta["funpay_chat_id"] = order.chat_id
                self._advance_stage(deal, DealStage.BOUGHT)
                await self._alert(
                    copy.OPERATOR_BOUGHT.format(
                        deal_id=deal.id[:8],
                        price=order.price,
                        username=deal.username,
                    )
                )
            elif deal.stage == DealStage.BUYING:
                self._advance_stage(deal, DealStage.BOUGHT)

            return await self._notify_seller(deal)
        except (GuardError, Exception) as exc:
            # Pricing / match problems → review (can retry); hard errors → fail
            msg = str(exc)
            if "margin" in msg or "match" in msg or "slip" in msg:
                return await self._review(deal, exc)
            return await self._fail(deal, exc)

    async def _notify_seller(self, deal: Deal) -> Deal:
        if deal.meta.get("seller_notified"):
            if deal.stage != DealStage.COMPLETED:
                return self._advance_stage(deal, DealStage.COMPLETED)
            return deal

        chat_id = str(deal.meta.get("funpay_chat_id") or "")
        if not chat_id:
            raise GuardError("missing FunPay chat_id for seller notify")
        if not deal.username:
            raise GuardError("missing username for seller notify")

        if deal.stage == DealStage.BOUGHT:
            self._advance_stage(deal, DealStage.NOTIFYING)

        if not self.settings.dry_run:
            self.settings.assert_live_allowed()
        text = copy.FUNPAY_SELLER_MESSAGE.format(username=deal.username)
        await self.funpay.send_message(chat_id, text)
        deal.meta["seller_notified"] = True
        deal.meta["seller_message"] = text
        self.store.upsert(deal)

        # Tell Playerok buyer we're done requesting delivery
        await self.playerok.send_message(
            deal.playerok_chat_id,
            copy.COMPLETED_TO_BUYER.format(username=deal.username),
        )
        self._advance_stage(deal, DealStage.COMPLETED)
        await self._alert(
            copy.OPERATOR_DONE.format(deal_id=deal.id[:8], username=deal.username)
        )
        return deal

    # ----------------------------------------------------------------- polling
    async def poll_once(self) -> dict[str, int]:
        async with self._lock:
            stats = {"ingested": 0, "advanced": 0, "stuck": 0}
            for sale in await self.playerok.list_new_sales():
                deal = await self.ingest_sale(sale)
                if deal:
                    stats["ingested"] += 1

            for deal in self.store.list_by_stages(ACTIVE_STAGES):
                before = deal.stage
                after = await self.advance(deal.id)
                if after and after.stage != before:
                    stats["advanced"] += 1

            stuck = self.store.mark_stuck(self.settings.stuck_deal_minutes)
            stats["stuck"] = len(stuck)
            return stats

    async def run_until_idle(self, *, max_ticks: int = 20) -> dict[str, int]:
        totals = {"ingested": 0, "advanced": 0, "stuck": 0, "ticks": 0}
        for i in range(max_ticks):
            totals["ticks"] = i + 1
            stats = await self.poll_once()
            for k in ("ingested", "advanced", "stuck"):
                totals[k] += stats[k]
            active = self.store.list_by_stages(ACTIVE_STAGES)
            if stats["ingested"] == 0 and stats["advanced"] == 0 and not active:
                break
            # Keep ticking while deals wait for username / mid-flight.
            if stats["ingested"] == 0 and stats["advanced"] == 0 and i >= 2:
                # Only awaiting_username left and nothing moved — stop.
                if all(d.stage == DealStage.AWAITING_USERNAME for d in active):
                    break
        return totals
