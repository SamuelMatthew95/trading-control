"""Deterministic-stage unit tests for the hybrid pipeline.

Pure functions only — no LLM, no Redis, no DB. These prove the safety gates
that surround the model: market validation, the candidate gate, the risk
engine (final authority), and position sizing.
"""

from __future__ import annotations

from api.constants import BlockReason, MarketDirection, PositionSide, ReviewResult, SizeHint
from api.services.hybrid.candidate_gate import build_candidate
from api.services.hybrid.config import HybridConfig
from api.services.hybrid.indicators import (
    Candle,
    atr_wilder,
    ema_last,
    relative_volume,
    rsi_wilder,
    vwap,
)
from api.services.hybrid.market_validator import validate_market
from api.services.hybrid.models import (
    BrokerState,
    DataQuality,
    InstructDecision,
    MarketSnapshot,
    PortfolioState,
    PositionState,
    ReasoningReview,
    RiskDecision,
    SignalSummary,
)
from api.services.hybrid.position_sizing import size_position
from api.services.hybrid.risk_engine import evaluate_risk
from api.services.hybrid.signal_engine import build_signal_summary

CFG = HybridConfig()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _market(**over) -> MarketSnapshot:
    base = dict(
        symbol="AAPL",
        market_open=True,
        tradable=True,
        broker_available=True,
        last_price=100.0,
        price_age_seconds=1.0,
        bid=99.99,
        ask=100.01,
        volume=10_000.0,
        relative_volume=1.5,
    )
    base.update(over)
    return MarketSnapshot(**base)


def _instruct(**over) -> InstructDecision:
    base = dict(
        action="buy",
        symbol="AAPL",
        confidence=0.9,
        setup_type="vwap_reclaim",
        thesis="t",
        risk_flags=[],
        suggested_entry=100.0,
        suggested_stop_loss=98.0,
        suggested_take_profit=106.0,
        reward_risk_ratio=3.0,
        position_size_hint=SizeHint.NORMAL,
        needs_reasoning_review=False,
        data_quality=DataQuality(
            price_fresh=True,
            volume_valid=True,
            indicators_complete=True,
            portfolio_state_complete=True,
            ledger_state_complete=True,
        ),
    )
    base.update(over)
    return InstructDecision(**base)


def _portfolio(**over) -> PortfolioState:
    base = dict(
        equity=100_000.0,
        cash=100_000.0,
        buying_power=100_000.0,
        open_positions_count=0,
        daily_drawdown_pct=0.0,
        complete=True,
        ledger_complete=True,
    )
    base.update(over)
    return PortfolioState(**base)


def _flat() -> PositionState:
    return PositionState(symbol="AAPL", side=PositionSide.FLAT, qty=0.0)


def _long() -> PositionState:
    return PositionState(symbol="AAPL", side=PositionSide.LONG, qty=10.0, entry_price=99.0)


# ---------------------------------------------------------------------------
# indicators
# ---------------------------------------------------------------------------


def test_ema_last_constant_series_equals_value():
    assert ema_last([5.0] * 30, 9) == 5.0


def test_rsi_all_gains_is_100():
    closes = [float(i) for i in range(1, 30)]
    assert rsi_wilder(closes, 14) == 100.0


def test_rsi_neutral_band_for_choppy_series():
    closes = [100.0, 101.0] * 20
    rsi = rsi_wilder(closes, 14)
    assert rsi is not None
    assert 40 < rsi < 70


def test_indicators_return_none_when_insufficient_data():
    assert ema_last([1.0, 2.0], 9) is None
    assert rsi_wilder([1.0, 2.0], 14) is None
    assert atr_wilder([], 14) is None


def test_vwap_weighted_average():
    candles = [Candle(10, 10, 10, 10, 1), Candle(20, 20, 20, 20, 3)]
    # (10*1 + 20*3) / 4 = 17.5
    assert vwap(candles) == 17.5


def test_relative_volume_ratio():
    candles = [Candle(1, 1, 1, 1, 100.0) for _ in range(20)] + [Candle(1, 1, 1, 1, 200.0)]
    assert relative_volume(candles, 20) == 2.0


# ---------------------------------------------------------------------------
# signal engine
# ---------------------------------------------------------------------------


def test_signal_engine_marks_incomplete_with_short_history():
    candles = [Candle(100, 101, 99, 100, 1000) for _ in range(5)]
    summary = build_signal_summary("AAPL", candles)
    assert summary.indicators_complete is False
    assert summary.missing_indicators  # explicitly names what is missing


def test_signal_engine_complete_uptrend_is_bullish():
    # Steadily rising closes → bullish trend, indicators all computable.
    candles = [
        Candle(open=100 + i, high=101 + i, low=99 + i, close=100 + i, volume=1000 + i * 10)
        for i in range(60)
    ]
    summary = build_signal_summary("AAPL", candles)
    assert summary.indicators_complete is True
    assert summary.raw_direction is MarketDirection.BULLISH
    assert 0.0 <= summary.confidence_seed <= 1.0


# ---------------------------------------------------------------------------
# market validator — each hard block fires before any LLM call
# ---------------------------------------------------------------------------


def test_market_closed_blocks():
    v = validate_market(_market(market_open=False), CFG)
    assert not v.passed and v.block_reason is BlockReason.MARKET_CLOSED


def test_stale_price_blocks():
    v = validate_market(_market(price_age_seconds=120.0), CFG)
    assert not v.passed and v.block_reason is BlockReason.PRICE_STALE


def test_unknown_price_age_treated_as_stale():
    v = validate_market(_market(price_age_seconds=None), CFG)
    assert not v.passed and v.block_reason is BlockReason.PRICE_STALE


def test_missing_price_blocks():
    v = validate_market(_market(last_price=None), CFG)
    assert not v.passed and v.block_reason is BlockReason.PRICE_MISSING


def test_wide_spread_blocks():
    v = validate_market(_market(bid=90.0, ask=110.0), CFG)
    assert not v.passed and v.block_reason is BlockReason.SPREAD_TOO_WIDE


def test_low_volume_blocks():
    v = validate_market(_market(relative_volume=0.1), CFG)
    assert not v.passed and v.block_reason is BlockReason.VOLUME_TOO_LOW


def test_not_tradable_blocks():
    v = validate_market(_market(tradable=False), CFG)
    assert not v.passed and v.block_reason is BlockReason.SYMBOL_NOT_TRADABLE


def test_broker_unavailable_blocks():
    v = validate_market(_market(broker_available=False), CFG)
    assert not v.passed and v.block_reason is BlockReason.BROKER_UNAVAILABLE


def test_valid_market_passes():
    assert validate_market(_market(), CFG).passed


# ---------------------------------------------------------------------------
# candidate gate — weak / incomplete signals never reach the model
# ---------------------------------------------------------------------------


def _signal(**over) -> SignalSummary:
    base = dict(
        symbol="AAPL",
        setup_type="vwap_reclaim",
        raw_direction=MarketDirection.BULLISH,
        confidence_seed=0.8,
        trend_score=0.9,
        momentum_score=0.8,
        liquidity_score=0.7,
        volatility_risk=0.2,
        indicators_complete=True,
        price_fresh=True,
        volume_valid=True,
        price_above_vwap=True,
        ema_9_above_ema_20=True,
        macd_bias=MarketDirection.BULLISH,
    )
    base.update(over)
    return SignalSummary(**base)


def test_strong_signal_is_candidate_sent_to_model():
    c = build_candidate(_signal(), CFG)
    assert c.candidate and c.send_to_model and c.direction == "long"


def test_weak_signal_not_sent_to_model():
    c = build_candidate(_signal(confidence_seed=0.3), CFG)
    assert not c.send_to_model and c.block_reason is BlockReason.WEAK_SIGNAL


def test_incomplete_indicators_not_sent_to_model():
    c = build_candidate(_signal(indicators_complete=False, missing_indicators=["rsi_14"]), CFG)
    assert not c.send_to_model and c.block_reason is BlockReason.INDICATORS_INCOMPLETE


def test_neutral_direction_not_sent_to_model():
    c = build_candidate(_signal(raw_direction=MarketDirection.NEUTRAL), CFG)
    assert not c.send_to_model and c.block_reason is BlockReason.NO_DIRECTION


# ---------------------------------------------------------------------------
# risk engine — the final authority overrides the model
# ---------------------------------------------------------------------------


def test_risk_approves_clean_buy():
    r = evaluate_risk(
        instruct=_instruct(),
        review=None,
        portfolio=_portfolio(),
        position=_flat(),
        broker=BrokerState(),
        config=CFG,
        current_price=100.0,
    )
    assert r.approved and r.decision == "buy"


def test_risk_blocks_low_confidence():
    r = evaluate_risk(
        instruct=_instruct(confidence=0.5),
        review=None,
        portfolio=_portfolio(),
        position=_flat(),
        broker=BrokerState(),
        config=CFG,
        current_price=100.0,
    )
    assert not r.approved and r.block_reason is BlockReason.LOW_CONFIDENCE


def test_risk_blocks_missing_stop_for_buy():
    r = evaluate_risk(
        instruct=_instruct(suggested_stop_loss=None),
        review=None,
        portfolio=_portfolio(),
        position=_flat(),
        broker=BrokerState(),
        config=CFG,
        current_price=100.0,
    )
    assert not r.approved and r.block_reason is BlockReason.MISSING_STOP_LOSS


def test_risk_blocks_low_reward_risk():
    r = evaluate_risk(
        instruct=_instruct(suggested_take_profit=101.0, reward_risk_ratio=0.5),
        review=None,
        portfolio=_portfolio(),
        position=_flat(),
        broker=BrokerState(),
        config=CFG,
        current_price=100.0,
    )
    assert not r.approved and r.block_reason is BlockReason.REWARD_RISK_TOO_LOW


def test_risk_blocks_duplicate_signal():
    r = evaluate_risk(
        instruct=_instruct(),
        review=None,
        portfolio=_portfolio(),
        position=_flat(),
        broker=BrokerState(),
        config=CFG,
        current_price=100.0,
        duplicate_signal=True,
    )
    assert not r.approved and r.block_reason is BlockReason.DUPLICATE_SIGNAL


def test_risk_blocks_open_order():
    r = evaluate_risk(
        instruct=_instruct(),
        review=None,
        portfolio=_portfolio(),
        position=_flat(),
        broker=BrokerState(open_order_exists=True),
        config=CFG,
        current_price=100.0,
    )
    assert not r.approved and r.block_reason is BlockReason.OPEN_ORDER_EXISTS


def test_risk_blocks_idempotency_reuse():
    r = evaluate_risk(
        instruct=_instruct(),
        review=None,
        portfolio=_portfolio(),
        position=_flat(),
        broker=BrokerState(),
        config=CFG,
        current_price=100.0,
        idempotency_reused=True,
    )
    assert not r.approved and r.block_reason is BlockReason.IDEMPOTENCY_REUSED


def test_risk_blocks_shorting_by_default():
    r = evaluate_risk(
        instruct=_instruct(action="sell", suggested_stop_loss=102.0, suggested_take_profit=94.0),
        review=None,
        portfolio=_portfolio(),
        position=_flat(),
        broker=BrokerState(),
        config=CFG,
        current_price=100.0,
    )
    assert not r.approved and r.block_reason is BlockReason.SHORTING_DISALLOWED


def test_risk_blocks_averaging_down_by_default():
    r = evaluate_risk(
        instruct=_instruct(),
        review=None,
        portfolio=_portfolio(open_positions_count=1),
        position=_long(),
        broker=BrokerState(),
        config=CFG,
        current_price=100.0,
    )
    assert not r.approved and r.block_reason is BlockReason.AVERAGING_DOWN_DISALLOWED


def test_risk_blocks_when_drawdown_elevated():
    r = evaluate_risk(
        instruct=_instruct(),
        review=None,
        portfolio=_portfolio(daily_drawdown_pct=0.05),
        position=_flat(),
        broker=BrokerState(),
        config=CFG,
        current_price=100.0,
    )
    assert not r.approved and r.block_reason is BlockReason.DAILY_LOSS_LIMIT


def test_risk_blocks_invalid_model_output():
    r = evaluate_risk(
        instruct=_instruct(),
        review=None,
        portfolio=_portfolio(),
        position=_flat(),
        broker=BrokerState(),
        config=CFG,
        current_price=100.0,
        instruct_valid=False,
    )
    assert not r.approved and r.block_reason is BlockReason.MODEL_OUTPUT_INVALID


def test_reasoning_downgrade_forces_hold():
    review = ReasoningReview(
        review_result=ReviewResult.DOWNGRADE_TO_HOLD,
        final_model_action="hold",
        confidence=0.4,
        reasoning_summary="unclear edge",
    )
    r = evaluate_risk(
        instruct=_instruct(),
        review=review,
        portfolio=_portfolio(),
        position=_flat(),
        broker=BrokerState(),
        config=CFG,
        current_price=100.0,
    )
    assert not r.approved and r.block_reason is BlockReason.REASONING_DOWNGRADE


def test_exit_recommendation_allowed_even_low_confidence():
    review = ReasoningReview(
        review_result=ReviewResult.EXIT_POSITION,
        final_model_action="sell",
        confidence=0.2,
        reasoning_summary="reduce risk",
    )
    r = evaluate_risk(
        instruct=_instruct(action="sell"),
        review=review,
        portfolio=_portfolio(),
        position=_long(),
        broker=BrokerState(),
        config=CFG,
        current_price=100.0,
    )
    assert r.approved and r.decision == "sell"


# ---------------------------------------------------------------------------
# position sizing — deterministic, rejects on zero
# ---------------------------------------------------------------------------


def _approved(**over) -> RiskDecision:
    base = dict(
        approved=True,
        decision="buy",
        symbol="AAPL",
        approved_entry=100.0,
        approved_stop_loss=98.0,
        approved_take_profit=106.0,
        size_multiplier=1.0,
    )
    base.update(over)
    return RiskDecision(**base)


def test_sizing_risk_based_quantity():
    order = size_position(
        risk=_approved(),
        portfolio=_portfolio(),
        position=_flat(),
        config=CFG,
        size_hint=SizeHint.NORMAL,
    )
    # risk_dollars = 100000 * 0.005 = 500; stop_distance = 2 → 250, capped by
    # symbol-exposure 10% (10000 / 100 = 100).
    assert order.reject_reason is None
    assert order.qty == 100.0


def test_sizing_zero_buying_power_rejects():
    order = size_position(
        risk=_approved(),
        portfolio=_portfolio(buying_power=0.0),
        position=_flat(),
        config=CFG,
        size_hint=SizeHint.NORMAL,
    )
    assert order.qty == 0.0 and order.reject_reason is BlockReason.SIZE_ZERO


def test_sizing_none_hint_rejects():
    order = size_position(
        risk=_approved(),
        portfolio=_portfolio(),
        position=_flat(),
        config=CFG,
        size_hint=SizeHint.NONE,
    )
    assert order.reject_reason is BlockReason.SIZE_ZERO


def test_sizing_closing_uses_position_qty():
    order = size_position(
        risk=_approved(decision="sell", approved_stop_loss=None),
        portfolio=_portfolio(),
        position=_long(),
        config=CFG,
        size_hint=SizeHint.NORMAL,
    )
    assert order.reject_reason is None and order.qty == 10.0


# ---------------------------------------------------------------------------
# strict LLM-output validation
# ---------------------------------------------------------------------------


def test_instruct_should_execute_is_always_false():
    d = _instruct()
    assert d.should_execute is False
    # Even if the model tries to set it true, the validator forces it false.
    d2 = InstructDecision.model_validate({**d.model_dump(), "should_execute": True})
    assert d2.should_execute is False
