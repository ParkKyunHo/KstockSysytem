"""Unit tests for ``src/core/v71/skills/avg_price_skill.py``.

Spec:
  - 02_TRADING_RULES.md §6.1 (core rules)
  - 02_TRADING_RULES.md §6.2 (add-buy: weighted avg + event reset + stage 1)
  - 02_TRADING_RULES.md §6.3 (event reset semantics)
  - 02_TRADING_RULES.md §6.4 (sell: avg unchanged)
"""

from __future__ import annotations

import pytest

from src.core.v71.position.state import PositionState
from src.core.v71.skills.avg_price_skill import (
    compute_weighted_average,
    update_position_after_buy,
    update_position_after_sell,
)
from src.core.v71.v71_constants import V71Constants as K

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_position() -> PositionState:
    """Brand-new position before its first buy."""
    return PositionState(
        position_id="pos-1",
        stock_code="005930",
        tracked_stock_id="t1",
        triggered_box_id="b1",
        path_type="PATH_A",
        weighted_avg_price=0,
        initial_avg_price=0,
        total_quantity=0,
        fixed_stop_price=0,
    )


def _populated_position(
    *,
    avg: int = 180_000,
    initial: int | None = None,
    qty: int = 100,
    profit_5: bool = False,
    profit_10: bool = False,
    ts_activated: bool = False,
    ts_base: int | None = None,
    ts_stop: int | None = None,
    ts_mult: float | None = None,
) -> PositionState:
    return PositionState(
        position_id="pos-1",
        stock_code="005930",
        tracked_stock_id="t1",
        triggered_box_id="b1",
        path_type="PATH_A",
        weighted_avg_price=avg,
        initial_avg_price=initial if initial is not None else avg,
        total_quantity=qty,
        fixed_stop_price=int(round(avg * (1 + K.STOP_LOSS_INITIAL_PCT))),
        profit_5_executed=profit_5,
        profit_10_executed=profit_10,
        ts_activated=ts_activated,
        ts_base_price=ts_base,
        ts_stop_price=ts_stop,
        ts_active_multiplier=ts_mult,
    )


# ---------------------------------------------------------------------------
# compute_weighted_average  (§6.2 formula)
# ---------------------------------------------------------------------------


class TestComputeWeightedAverage:
    def test_first_buy_returns_new_price(self):
        assert compute_weighted_average(0, 0, 100, 18_000) == 18_000

    def test_basic_example_from_prd(self):
        # §6.3 example: 70 @ 180,000 + 100 @ 175,000 -> 177,058
        assert (
            compute_weighted_average(70, 180_000, 100, 175_000)
            == round((70 * 180_000 + 100 * 175_000) / 170)
        )

    def test_pyramid_buy_increases_avg(self):
        # Existing 100 @ 180k, add 50 @ 185k
        assert (
            compute_weighted_average(100, 180_000, 50, 185_000)
            == round((100 * 180_000 + 50 * 185_000) / 150)
        )

    def test_zero_total_raises(self):
        with pytest.raises(ValueError):
            compute_weighted_average(0, 0, 0, 18_000)

    def test_negative_qty_raises(self):
        with pytest.raises(ValueError):
            compute_weighted_average(-1, 18_000, 50, 17_000)

    def test_zero_new_price_raises(self):
        with pytest.raises(ValueError):
            compute_weighted_average(100, 18_000, 50, 0)


# ---------------------------------------------------------------------------
# update_position_after_buy  (§6.2)
# ---------------------------------------------------------------------------


class TestFirstBuy:
    def test_first_buy_sets_initial_and_avg(self):
        p = _empty_position()
        update = update_position_after_buy(p, buy_price=18_000, buy_quantity=100)
        assert update.weighted_avg_price == 18_000
        assert update.initial_avg_price == 18_000
        assert update.total_quantity == 100
        # Stage 1 stop = 18_000 * 0.95
        assert update.fixed_stop_price == 17_100
        # First buy is not an "events_reset" event (nothing to reset).
        assert update.events_reset is False
        assert update.profit_5_executed is False
        assert update.profit_10_executed is False
        # TS preserved (still inactive on a fresh position).
        assert update.ts_base_price is None
        assert update.ts_activated is False

    def test_first_buy_rejects_non_positive(self):
        p = _empty_position()
        with pytest.raises(ValueError):
            update_position_after_buy(p, buy_price=0, buy_quantity=100)
        with pytest.raises(ValueError):
            update_position_after_buy(p, buy_price=18_000, buy_quantity=0)


class TestAddBuy:
    def test_pyramid_buy_recomputes_weighted_avg(self):
        # 100 @ 180k -> add 50 @ 185k -> 150 @ 181_667
        p = _populated_position(avg=180_000, qty=100)
        update = update_position_after_buy(p, buy_price=185_000, buy_quantity=50)
        expected_avg = round((100 * 180_000 + 50 * 185_000) / 150)
        assert update.weighted_avg_price == expected_avg
        assert update.total_quantity == 150
        assert update.events_reset is True

    def test_pyramid_resets_event_flags(self):
        p = _populated_position(
            avg=180_000, qty=70, profit_5=True, profit_10=False
        )
        update = update_position_after_buy(p, buy_price=175_000, buy_quantity=100)
        assert update.profit_5_executed is False  # reset
        assert update.profit_10_executed is False
        assert update.events_reset is True

    def test_pyramid_falls_back_to_stage_1_stop(self):
        # 100 @ 180k, profit_5_executed True -> stop was -2% = 176_400
        # Add buy 50 @ 185k -> new avg 181_667 -> stop = 181_667 * 0.95
        p = _populated_position(
            avg=180_000, qty=100, profit_5=True
        )
        update = update_position_after_buy(p, buy_price=185_000, buy_quantity=50)
        expected_stop = int(round(update.weighted_avg_price * 0.95))
        assert update.fixed_stop_price == expected_stop
        # Stage 1 stop should be LOWER than the pre-buy -2% stop.
        assert update.fixed_stop_price < int(180_000 * 0.98)

    def test_pyramid_preserves_initial_avg(self):
        p = _populated_position(avg=180_000, initial=180_000, qty=100)
        update = update_position_after_buy(p, buy_price=185_000, buy_quantity=50)
        assert update.initial_avg_price == 180_000

    def test_pyramid_preserves_ts_base(self):
        # Position rallied to 200k high before pyramid buy.
        p = _populated_position(
            avg=180_000, qty=100,
            ts_activated=True, ts_base=200_000,
            ts_stop=192_000, ts_mult=4.0,
            profit_5=True,
        )
        update = update_position_after_buy(p, buy_price=185_000, buy_quantity=50)
        assert update.ts_base_price == 200_000  # preserved
        assert update.ts_active_multiplier == 4.0
        assert update.ts_stop_price == 192_000


# ---------------------------------------------------------------------------
# update_position_after_sell  (§6.4)
# ---------------------------------------------------------------------------


class TestSell:
    def test_sell_keeps_avg_unchanged(self):
        p = _populated_position(avg=180_000, qty=100)
        update = update_position_after_sell(p, sell_quantity=30)
        assert update.weighted_avg_price == 180_000  # §6.4
        assert update.total_quantity == 70
        assert update.events_reset is False

    def test_sell_preserves_event_flags(self):
        p = _populated_position(
            avg=180_000, qty=100, profit_5=True
        )
        update = update_position_after_sell(p, sell_quantity=30)
        assert update.profit_5_executed is True  # NOT reset on sell

    def test_sell_does_not_advance_stop(self):
        """The skill keeps fixed_stop unchanged. The caller (V71PositionManager)
        decides whether to advance via stage_after_partial_exit()."""
        p = _populated_position(avg=180_000, qty=100)
        original_stop = p.fixed_stop_price
        update = update_position_after_sell(p, sell_quantity=30)
        assert update.fixed_stop_price == original_stop

    def test_sell_full_quantity_zeros_total(self):
        p = _populated_position(avg=180_000, qty=100)
        update = update_position_after_sell(p, sell_quantity=100)
        assert update.total_quantity == 0
        assert update.weighted_avg_price == 180_000  # ledger preserved

    def test_sell_too_many_raises(self):
        p = _populated_position(avg=180_000, qty=100)
        with pytest.raises(ValueError, match="exceeds"):
            update_position_after_sell(p, sell_quantity=101)

    def test_sell_zero_or_negative_raises(self):
        p = _populated_position(avg=180_000, qty=100)
        with pytest.raises(ValueError):
            update_position_after_sell(p, sell_quantity=0)
        with pytest.raises(ValueError):
            update_position_after_sell(p, sell_quantity=-1)


# ---------------------------------------------------------------------------
# §6.3 scenario: add buy AFTER profit_5 already executed
# ---------------------------------------------------------------------------


class TestPyramidAfterPartial:
    def test_full_scenario(self):
        """PRD §6.3 example sequence -- this is the canonical test."""
        # Step 1: first buy 100 @ 180k.
        p = _empty_position()
        u1 = update_position_after_buy(p, buy_price=180_000, buy_quantity=100)
        # Apply (we use a fresh PositionState for clarity).
        p = _populated_position(avg=u1.weighted_avg_price, qty=u1.total_quantity)

        # Step 2: +5% partial -> sell 30, keep 70 @ 180_000.
        u2 = update_position_after_sell(p, sell_quantity=30)
        # Mark profit_5 in our own simulation (the real thing is done by
        # the position manager, not the skill).
        p = _populated_position(
            avg=u2.weighted_avg_price,
            qty=u2.total_quantity,
            profit_5=True,
        )
        assert p.weighted_avg_price == 180_000
        assert p.total_quantity == 70

        # Step 3: 2nd box buy 100 @ 175_000 -> recompute + reset.
        u3 = update_position_after_buy(p, buy_price=175_000, buy_quantity=100)
        expected_avg = round((70 * 180_000 + 100 * 175_000) / 170)
        assert u3.weighted_avg_price == expected_avg  # ~177_059
        assert u3.total_quantity == 170
        assert u3.profit_5_executed is False  # RESET
        assert u3.events_reset is True
        # New +5% threshold = expected_avg * 1.05 (skill doesn't compute,
        # but we sanity-check stop is at stage 1).
        assert u3.fixed_stop_price == int(round(expected_avg * 0.95))
