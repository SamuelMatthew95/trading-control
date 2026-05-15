"""Unit tests for api/services/execution/position_math.py.

All functions are pure (no IO, no async) — no mocking needed.
"""

import pytest

from api.constants import FieldName, OrderSide, PositionSide
from api.services.execution.position_math import (
    apply_signed_delta,
    compute_pnl_percent,
    compute_realized_pnl,
    is_round_trip_close,
    reject_unmatched_sell,
)

# ---------------------------------------------------------------------------
# compute_realized_pnl
# ---------------------------------------------------------------------------


class TestComputeRealizedPnl:
    def _pos(self, side, qty, entry_price):
        return {FieldName.SIDE: side, FieldName.QTY: qty, FieldName.ENTRY_PRICE: entry_price}

    def test_long_position_sell_profit(self):
        pos = self._pos(PositionSide.LONG, 2.0, 100.0)
        pnl = compute_realized_pnl(pos, OrderSide.SELL, 2.0, 110.0)
        assert pnl == pytest.approx(20.0)

    def test_long_position_sell_loss(self):
        pos = self._pos(PositionSide.LONG, 1.0, 200.0)
        pnl = compute_realized_pnl(pos, OrderSide.SELL, 1.0, 150.0)
        assert pnl == pytest.approx(-50.0)

    def test_short_position_buy_profit(self):
        pos = self._pos(PositionSide.SHORT, 1.0, 200.0)
        pnl = compute_realized_pnl(pos, OrderSide.BUY, 1.0, 150.0)
        assert pnl == pytest.approx(50.0)

    def test_short_position_buy_loss(self):
        pos = self._pos(PositionSide.SHORT, 1.0, 100.0)
        pnl = compute_realized_pnl(pos, OrderSide.BUY, 1.0, 120.0)
        assert pnl == pytest.approx(-20.0)

    def test_adding_to_long_position_returns_zero(self):
        """Opening or adding to a position has no realized PnL."""
        pos = self._pos(PositionSide.LONG, 1.0, 100.0)
        pnl = compute_realized_pnl(pos, OrderSide.BUY, 1.0, 110.0)
        assert pnl == pytest.approx(0.0)

    def test_empty_position_returns_zero(self):
        pnl = compute_realized_pnl({}, OrderSide.SELL, 1.0, 110.0)
        assert pnl == pytest.approx(0.0)

    def test_partial_close_uses_closed_qty(self):
        """Selling 1 of 2 units should compute PnL on 1 unit only."""
        pos = self._pos(PositionSide.LONG, 2.0, 100.0)
        pnl = compute_realized_pnl(pos, OrderSide.SELL, 1.0, 120.0)
        assert pnl == pytest.approx(20.0)

    def test_zero_prior_qty_returns_zero(self):
        pos = self._pos(PositionSide.LONG, 0.0, 100.0)
        pnl = compute_realized_pnl(pos, OrderSide.SELL, 1.0, 110.0)
        assert pnl == pytest.approx(0.0)

    def test_uses_short_side_alias(self):
        """PositionSide.SHORT as trade side should match short position."""
        pos = self._pos(PositionSide.SHORT, 1.0, 200.0)
        pnl = compute_realized_pnl(pos, PositionSide.LONG, 1.0, 180.0)
        assert pnl == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# compute_pnl_percent
# ---------------------------------------------------------------------------


class TestComputePnlPercent:
    def _pos(self, qty):
        return {FieldName.QTY: qty}

    def test_long_profit_percent(self):
        pos = self._pos(2.0)
        pct = compute_pnl_percent(pos, OrderSide.SELL, 2.0, 100.0, 20.0)
        # 20 / (100 * 2) * 100 = 10%
        assert pct == pytest.approx(10.0)

    def test_zero_realized_returns_zero(self):
        pos = self._pos(1.0)
        pct = compute_pnl_percent(pos, OrderSide.SELL, 1.0, 100.0, 0.0)
        assert pct == pytest.approx(0.0)

    def test_zero_entry_price_returns_zero(self):
        pos = self._pos(1.0)
        pct = compute_pnl_percent(pos, OrderSide.SELL, 1.0, 0.0, 10.0)
        assert pct == pytest.approx(0.0)

    def test_partial_close_uses_closed_qty(self):
        """Closing 1 of 3 units: cost basis should be 1 * entry, not 3 * entry."""
        pos = self._pos(3.0)
        pct = compute_pnl_percent(pos, OrderSide.SELL, 1.0, 100.0, 10.0)
        # 10 / (100 * 1) * 100 = 10%
        assert pct == pytest.approx(10.0)

    def test_loss_returns_negative_percent(self):
        pos = self._pos(1.0)
        pct = compute_pnl_percent(pos, OrderSide.SELL, 1.0, 200.0, -40.0)
        # -40 / (200 * 1) * 100 = -20%
        assert pct == pytest.approx(-20.0)


# ---------------------------------------------------------------------------
# is_round_trip_close
# ---------------------------------------------------------------------------


class TestIsRoundTripClose:
    def _pos(self, side, qty):
        return {FieldName.SIDE: side, FieldName.QTY: qty}

    def test_sell_closes_long(self):
        assert is_round_trip_close(self._pos(PositionSide.LONG, 1.0), OrderSide.SELL, 1.0)

    def test_buy_closes_short(self):
        assert is_round_trip_close(self._pos(PositionSide.SHORT, 1.0), OrderSide.BUY, 1.0)

    def test_buy_adds_to_long_not_close(self):
        assert not is_round_trip_close(self._pos(PositionSide.LONG, 1.0), OrderSide.BUY, 1.0)

    def test_sell_adds_to_short_not_close(self):
        assert not is_round_trip_close(self._pos(PositionSide.SHORT, 1.0), OrderSide.SELL, 1.0)

    def test_flat_position_not_close(self):
        assert not is_round_trip_close(self._pos(PositionSide.FLAT, 0.0), OrderSide.SELL, 1.0)

    def test_empty_position_not_close(self):
        assert not is_round_trip_close({}, OrderSide.SELL, 1.0)

    def test_short_side_alias_closes_long(self):
        """PositionSide.SHORT as sell side should also trigger close."""
        assert is_round_trip_close(self._pos(PositionSide.LONG, 1.0), PositionSide.SHORT, 1.0)


# ---------------------------------------------------------------------------
# reject_unmatched_sell
# ---------------------------------------------------------------------------


class TestRejectUnmatchedSell:
    def _pos(self, side, qty):
        return {FieldName.SIDE: side, FieldName.QTY: qty}

    def test_sell_with_no_long_rejected(self):
        assert reject_unmatched_sell(OrderSide.SELL, self._pos(PositionSide.FLAT, 0.0))

    def test_sell_with_long_not_rejected(self):
        assert not reject_unmatched_sell(OrderSide.SELL, self._pos(PositionSide.LONG, 1.0))

    def test_buy_never_rejected(self):
        assert not reject_unmatched_sell(OrderSide.BUY, self._pos(PositionSide.FLAT, 0.0))

    def test_sell_with_short_position_rejected(self):
        """Selling while short (no long to close) should reject."""
        assert reject_unmatched_sell(OrderSide.SELL, self._pos(PositionSide.SHORT, 1.0))

    def test_sell_with_empty_position_rejected(self):
        assert reject_unmatched_sell(OrderSide.SELL, {})

    def test_short_side_alias_with_long_not_rejected(self):
        assert not reject_unmatched_sell(PositionSide.SHORT, self._pos(PositionSide.LONG, 2.0))


# ---------------------------------------------------------------------------
# apply_signed_delta
# ---------------------------------------------------------------------------


class TestApplySignedDelta:
    BASE = {"strategy_id": "s1", "symbol": "BTC/USD"}

    def _pos(self, side, qty, entry_price=100.0):
        return {
            FieldName.SIDE: side,
            FieldName.QTY: qty,
            FieldName.ENTRY_PRICE: entry_price,
        }

    def test_buy_adds_to_long(self):
        existing = self._pos(PositionSide.LONG, 1.0, 100.0)
        result = apply_signed_delta(
            existing, OrderSide.BUY, 1.0, 110.0, strategy_id="s1", symbol="BTC/USD"
        )
        assert result is not None
        assert result[FieldName.QTY] == pytest.approx(2.0)
        assert result[FieldName.SIDE] == PositionSide.LONG
        assert result[FieldName.ENTRY_PRICE] == pytest.approx(100.0)  # entry price preserved

    def test_sell_reduces_long(self):
        existing = self._pos(PositionSide.LONG, 2.0, 100.0)
        result = apply_signed_delta(
            existing, OrderSide.SELL, 1.0, 110.0, strategy_id="s1", symbol="BTC/USD"
        )
        assert result is not None
        assert result[FieldName.QTY] == pytest.approx(1.0)
        assert result[FieldName.SIDE] == PositionSide.LONG

    def test_sell_all_returns_none(self):
        """Closing entire position → flat → None returned."""
        existing = self._pos(PositionSide.LONG, 1.0, 100.0)
        result = apply_signed_delta(
            existing, OrderSide.SELL, 1.0, 110.0, strategy_id="s1", symbol="BTC/USD"
        )
        assert result is None

    def test_buy_closes_short(self):
        existing = self._pos(PositionSide.SHORT, 1.0, 200.0)
        result = apply_signed_delta(
            existing, OrderSide.BUY, 1.0, 190.0, strategy_id="s1", symbol="BTC/USD"
        )
        assert result is None

    def test_buy_reduces_short(self):
        existing = self._pos(PositionSide.SHORT, 2.0, 200.0)
        result = apply_signed_delta(
            existing, OrderSide.BUY, 1.0, 190.0, strategy_id="s1", symbol="BTC/USD"
        )
        assert result is not None
        assert result[FieldName.QTY] == pytest.approx(1.0)
        assert result[FieldName.SIDE] == PositionSide.SHORT

    def test_result_carries_market_value(self):
        existing = self._pos(PositionSide.LONG, 1.0, 100.0)
        result = apply_signed_delta(
            existing, OrderSide.BUY, 1.0, 110.0, strategy_id="s1", symbol="BTC/USD"
        )
        assert result is not None
        assert result[FieldName.MARKET_VALUE] == pytest.approx(2.0 * 110.0)

    def test_result_carries_strategy_and_symbol(self):
        existing = self._pos(PositionSide.LONG, 1.0)
        result = apply_signed_delta(
            existing, OrderSide.BUY, 0.5, 105.0, strategy_id="strat-A", symbol="ETH/USD"
        )
        assert result is not None
        assert result[FieldName.STRATEGY_ID] == "strat-A"
        assert result[FieldName.SYMBOL] == "ETH/USD"

    def test_tiny_residual_treated_as_flat(self):
        """Floating-point residual < 1e-9 is treated as flat (returns None)."""
        existing = self._pos(PositionSide.LONG, 1.0, 100.0)
        result = apply_signed_delta(
            existing, OrderSide.SELL, 1.0 - 1e-12, 110.0, strategy_id="s1", symbol="BTC/USD"
        )
        # residual is ~1e-12, below 1e-9 threshold
        assert result is None
