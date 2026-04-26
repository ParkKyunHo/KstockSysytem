"""Unit tests for ``src/core/v71/skills/reconciliation_skill.py``.

Spec:
  - 02_TRADING_RULES.md §7.2~§7.5 (Scenarios A/B/C/D)
  - 02_TRADING_RULES.md §7.3 case 3 (dual-path proportional split)
"""

from __future__ import annotations

import pytest

from src.core.v71.position.state import PositionState
from src.core.v71.skills.reconciliation_skill import (
    KiwoomBalance,
    ReconciliationCase,
    SystemPosition,
    classify_case,
    compute_proportional_split,
)


def _pos(*, path: str, qty: int, status: str = "OPEN") -> PositionState:
    return PositionState(
        position_id=f"pid-{path}",
        stock_code="005930",
        tracked_stock_id="t1",
        triggered_box_id="b1",
        path_type=path,
        weighted_avg_price=18_000,
        initial_avg_price=18_000,
        total_quantity=qty,
        fixed_stop_price=17_100,
        status=status,
    )


# ---------------------------------------------------------------------------
# classify_case  (§7 truth table)
# ---------------------------------------------------------------------------


class TestClassifyCase:
    def test_e_full_match(self):
        assert classify_case(100, 100, has_active_tracking=False) == (
            ReconciliationCase.E_FULL_MATCH
        )

    def test_a_system_plus_buy(self):
        # Broker holds more than system knows -> user added.
        assert classify_case(150, 100, has_active_tracking=False) == (
            ReconciliationCase.A_SYSTEM_PLUS_MANUAL_BUY
        )

    def test_b_system_plus_sell(self):
        # Broker holds less than system knows -> user sold.
        assert classify_case(50, 100, has_active_tracking=True) == (
            ReconciliationCase.B_SYSTEM_PLUS_MANUAL_SELL
        )

    def test_c_tracked_but_manual_buy(self):
        # System holds 0 but tracking exists -> user bought before trigger.
        assert classify_case(50, 0, has_active_tracking=True) == (
            ReconciliationCase.C_TRACKED_BUT_MANUAL_BUY
        )

    def test_d_untracked_manual_buy(self):
        # System holds 0 and no tracking -> ad-hoc user buy.
        assert classify_case(50, 0, has_active_tracking=False) == (
            ReconciliationCase.D_UNTRACKED_MANUAL_BUY
        )

    def test_negative_quantities_rejected(self):
        with pytest.raises(ValueError):
            classify_case(-1, 0, has_active_tracking=False)
        with pytest.raises(ValueError):
            classify_case(10, -1, has_active_tracking=False)

    def test_full_sell_classified_as_b(self):
        # User sold all -- broker=0 but system still knows the position.
        assert classify_case(0, 10, has_active_tracking=False) == (
            ReconciliationCase.B_SYSTEM_PLUS_MANUAL_SELL
        )


# ---------------------------------------------------------------------------
# compute_proportional_split (§7.3 case 3)
# ---------------------------------------------------------------------------


class TestProportionalSplit:
    def test_zero_sell_returns_zeros(self):
        assert compute_proportional_split(0, 100, 50) == (0, 0)

    def test_only_path_a_holding(self):
        assert compute_proportional_split(40, 100, 0) == (40, 0)

    def test_only_path_b_holding(self):
        assert compute_proportional_split(40, 0, 100) == (0, 40)

    def test_clean_proportional_split(self):
        # 100 + 100 holdings, sell 20 -> 10 + 10
        assert compute_proportional_split(20, 100, 100) == (10, 10)

    def test_prd_example_larger_first_rounding(self):
        """PRD §7.3 example: 100/50 holdings, sell 10 -> 7 + 3 (A larger)."""
        assert compute_proportional_split(10, 100, 50) == (7, 3)

    def test_larger_path_first_when_b_larger(self):
        """Mirror: 50/100 holdings, sell 10 -> 3 + 7 (B larger)."""
        assert compute_proportional_split(10, 50, 100) == (3, 7)

    def test_tie_breaks_toward_path_a(self):
        """When path_a_qty == path_b_qty, leftover goes to PATH_A."""
        # 100 / 100, sell 21 -> 10.5 + 10.5; floor (10, 10) leftover 1 -> A
        assert compute_proportional_split(21, 100, 100) == (11, 10)

    def test_full_sell_returns_full_split(self):
        # Sell everything -> PATH_A=100, PATH_B=50 (no rounding needed)
        assert compute_proportional_split(150, 100, 50) == (100, 50)

    def test_sum_equals_sell_quantity_property(self):
        """Property: a + b == sell_quantity for any reasonable input."""
        for sq, pa, pb in [
            (0, 0, 0), (1, 1, 0), (1, 0, 1),
            (5, 7, 3), (5, 3, 7), (5, 5, 5),
            (17, 100, 50), (33, 50, 100),
            (1000, 1234, 5678),
        ]:
            a, b = compute_proportional_split(sq, pa, pb)
            assert a + b == sq, f"sum mismatch on ({sq}, {pa}, {pb}): {a}+{b}"
            assert 0 <= a <= pa
            assert 0 <= b <= pb

    def test_sell_more_than_total_raises(self):
        with pytest.raises(ValueError, match="exceeds"):
            compute_proportional_split(200, 100, 50)

    def test_negative_inputs_rejected(self):
        with pytest.raises(ValueError):
            compute_proportional_split(-1, 100, 50)
        with pytest.raises(ValueError):
            compute_proportional_split(10, -1, 50)


# ---------------------------------------------------------------------------
# SystemPosition aggregation
# ---------------------------------------------------------------------------


class TestSystemPositionAggregation:
    def test_total_qty_sums_all_paths(self):
        sp = SystemPosition(
            stock_code="005930",
            positions=[
                _pos(path="PATH_A", qty=100),
                _pos(path="PATH_B", qty=50),
                _pos(path="MANUAL", qty=30),
            ],
        )
        assert sp.total_qty() == 180

    def test_system_total_qty_excludes_manual(self):
        sp = SystemPosition(
            stock_code="005930",
            positions=[
                _pos(path="PATH_A", qty=100),
                _pos(path="PATH_B", qty=50),
                _pos(path="MANUAL", qty=30),
            ],
        )
        assert sp.system_total_qty() == 150

    def test_manual_total_qty(self):
        sp = SystemPosition(
            stock_code="005930",
            positions=[
                _pos(path="PATH_A", qty=100),
                _pos(path="MANUAL", qty=30),
            ],
        )
        assert sp.manual_total_qty() == 30

    def test_empty_aggregation(self):
        sp = SystemPosition(stock_code="005930", positions=[])
        assert sp.total_qty() == 0
        assert sp.system_total_qty() == 0
        assert sp.manual_total_qty() == 0


# ---------------------------------------------------------------------------
# KiwoomBalance smoke
# ---------------------------------------------------------------------------


class TestKiwoomBalance:
    def test_dataclass_constructs(self):
        kb = KiwoomBalance(stock_code="005930", quantity=100, avg_price=18_000)
        assert kb.stock_code == "005930"
        assert kb.quantity == 100
        assert kb.avg_price == 18_000
