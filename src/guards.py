from __future__ import annotations

import re
from difflib import SequenceMatcher

from src.models import ALLOWED_TRANSITIONS, DealStage


class GuardError(Exception):
    pass


_WS = re.compile(r"\s+")
_NOISE = re.compile(r"[^\w\sа-яА-ЯёЁ]+", re.UNICODE)


def normalize_title(title: str) -> str:
    cleaned = _NOISE.sub(" ", title.lower())
    return _WS.sub(" ", cleaned).strip()


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def assert_transition(current: DealStage, nxt: DealStage) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if nxt not in allowed:
        raise GuardError(f"illegal stage jump: {current} → {nxt}")


def assert_price_positive(price: float, label: str = "price") -> None:
    if price is None or price <= 0:
        raise GuardError(f"{label} must be > 0, got {price!r}")


def assert_within_max_buy(price: float, max_buy: float) -> None:
    if price > max_buy:
        raise GuardError(f"FunPay price {price} exceeds max_funpay_price {max_buy}")


def assert_margin(buy: float, sell: float, min_margin_pct: float) -> float:
    """sell = Playerok revenue, buy = FunPay cost."""
    assert_price_positive(buy, "funpay buy")
    assert_price_positive(sell, "playerok sale")
    if sell <= buy:
        raise GuardError(f"sale {sell} must exceed buy {buy}")
    margin = ((sell - buy) / buy) * 100.0
    if margin < min_margin_pct:
        raise GuardError(
            f"margin {margin:.2f}% < min_margin_pct {min_margin_pct}%"
        )
    return margin


def assert_no_slippage(quoted: float, live: float, slippage_pct: float) -> None:
    assert_price_positive(quoted, "quoted")
    assert_price_positive(live, "live")
    if live > quoted * (1 + slippage_pct / 100.0):
        raise GuardError(
            f"price slipped quoted={quoted} live={live} allowed={slippage_pct}%"
        )


def assert_title_match(sale_title: str, lot_title: str, min_ratio: float) -> float:
    ratio = title_similarity(sale_title, lot_title)
    if ratio < min_ratio:
        raise GuardError(
            f"title mismatch ({ratio:.2f} < {min_ratio}): "
            f"{sale_title!r} vs {lot_title!r}"
        )
    return ratio


def sale_matches_filter(
    *,
    lot_id: str,
    title: str,
    allowlist: set[str],
    keywords: list[str],
) -> str | None:
    """Return match reason or None if sale should be ignored."""
    if allowlist:
        if lot_id in allowlist:
            return f"lot_id:{lot_id}"
        return None
    norm = normalize_title(title)
    for kw in keywords:
        if kw and kw in norm:
            return f"keyword:{kw}"
    return None
