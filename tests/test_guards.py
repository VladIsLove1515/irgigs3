import pytest

from src.guards import (
    GuardError,
    assert_margin,
    assert_no_slippage,
    assert_title_match,
    assert_transition,
    sale_matches_filter,
)
from src.models import DealStage


def test_margin_ok_and_too_small():
    assert assert_margin(350, 450, 15) == pytest.approx(28.571, rel=1e-3)
    with pytest.raises(GuardError, match="margin"):
        assert_margin(350, 360, 15)


def test_slippage_and_title():
    assert_no_slippage(100, 102, 3)
    with pytest.raises(GuardError, match="slipped"):
        assert_no_slippage(100, 110, 3)
    assert assert_title_match(
        "Steam Gift Card 500 RUB", "Steam Gift Card 500 RUB", 0.55
    ) == 1.0
    with pytest.raises(GuardError, match="mismatch"):
        assert_title_match("Steam Gift Card", "Random CS2 sticker", 0.55)


def test_illegal_transition():
    with pytest.raises(GuardError, match="illegal"):
        assert_transition(DealStage.NEW, DealStage.COMPLETED)
    assert_transition(DealStage.NEW, DealStage.READY)


def test_sale_filter_keywords_and_allowlist():
    assert sale_matches_filter(
        lot_id="x",
        title="Discord Nitro 1 Month",
        allowlist=set(),
        keywords=["nitro"],
    ) == "keyword:nitro"
    assert sale_matches_filter(
        lot_id="lot-1",
        title="anything",
        allowlist={"lot-1"},
        keywords=["nitro"],
    ) == "lot_id:lot-1"
    assert (
        sale_matches_filter(
            lot_id="other",
            title="anything",
            allowlist={"lot-1"},
            keywords=["nitro"],
        )
        is None
    )
