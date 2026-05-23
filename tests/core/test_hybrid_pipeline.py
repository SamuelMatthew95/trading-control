"""End-to-end orchestrator tests for the hybrid decision pipeline.

A fake LLM (injected callable) and a fake bus stand in for the real provider
and Redis. These prove the system-level safety guarantees:

  - the LLM is never called when market validation / candidate gate fails
  - malformed model JSON becomes a safe HOLD, never an execution
  - the reasoning model is only called for ambiguous / high-risk cases
  - the deterministic risk engine overrides the model
  - sizing is deterministic and qty==0 blocks execution
  - a decision is only published to STREAM_DECISIONS when risk-approved
  - durable lifecycle events carry trace_id, decision_id, event_version
"""

from __future__ import annotations

import json

from api.constants import (
    HYBRID_LIFECYCLE_EVENT_TYPE,
    STREAM_DECISIONS,
    STREAM_TRADE_LIFECYCLE,
    BlockReason,
    FieldName,
    LifecycleStage,
    MarketDirection,
    PositionSide,
)
from api.services.hybrid.config import HybridConfig
from api.services.hybrid.models import (
    BrokerState,
    MarketSnapshot,
    PortfolioState,
    PositionState,
    SignalSummary,
)
from api.services.hybrid.pipeline import HybridDecisionPipeline

CFG = HybridConfig()


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, stream: str, event: dict, maxlen: int | None = None) -> str:
        self.events.append((stream, event))
        return "1-0"

    def streams(self) -> list[str]:
        return [s for s, _ in self.events]

    def stages(self) -> list[str]:
        return [e[FieldName.STAGE] for s, e in self.events if s == STREAM_TRADE_LIFECYCLE]


class FakeLLM:
    """Returns canned JSON; routes by system prompt (instruct vs reasoning)."""

    def __init__(self, instruct: str | None = None, reasoning: str | None = None) -> None:
        self.instruct = instruct
        self.reasoning = reasoning
        self.instruct_calls = 0
        self.reasoning_calls = 0

    async def __call__(self, prompt, system_prompt, trace_id, task_type):
        if "risk reviewer" in system_prompt:
            self.reasoning_calls += 1
            return self.reasoning or "{}", 10, 0.0
        self.instruct_calls += 1
        return self.instruct or "{}", 10, 0.0

    @property
    def total_calls(self) -> int:
        return self.instruct_calls + self.reasoning_calls


# ---------------------------------------------------------------------------
# input builders
# ---------------------------------------------------------------------------


def good_market(**over) -> MarketSnapshot:
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


def strong_signal(**over) -> SignalSummary:
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


def flat_portfolio(**over) -> PortfolioState:
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


def flat_position() -> PositionState:
    return PositionState(symbol="AAPL", side=PositionSide.FLAT, qty=0.0)


def instruct_json(**over) -> str:
    payload = dict(
        action="buy",
        symbol="AAPL",
        confidence=0.9,
        setup_type="vwap_reclaim",
        thesis="momentum reclaim",
        supporting_signals=["price_above_vwap"],
        conflicting_signals=[],
        risk_flags=[],
        suggested_entry=100.0,
        suggested_stop_loss=98.0,
        suggested_take_profit=106.0,
        reward_risk_ratio=3.0,
        position_size_hint="normal",
        needs_reasoning_review=False,
        data_quality=dict(
            price_fresh=True,
            volume_valid=True,
            indicators_complete=True,
            portfolio_state_complete=True,
            ledger_state_complete=True,
        ),
        should_execute=False,
    )
    payload.update(over)
    return json.dumps(payload)


def reasoning_json(**over) -> str:
    payload = dict(
        review_result="continue_to_risk_review",
        final_model_action="buy",
        confidence=0.8,
        reasoning_summary="edge is real",
        main_concern=None,
        model_disagreements=[],
        additional_risk_flags=[],
        recommended_size_multiplier=1.0,
        required_risk_checks=[],
    )
    payload.update(over)
    return json.dumps(payload)


async def _run(
    pipeline: HybridDecisionPipeline,
    *,
    market=None,
    signal=None,
    portfolio=None,
    position=None,
    broker=None,
    **kw,
):
    return await pipeline.decide(
        market=market or good_market(),
        signal=signal or strong_signal(),
        portfolio=portfolio or flat_portfolio(),
        position=position or flat_position(),
        broker=broker or BrokerState(),
        **kw,
    )


# ---------------------------------------------------------------------------
# pre-LLM hard gates — model is NOT called
# ---------------------------------------------------------------------------


async def test_stale_price_blocks_before_model_call():
    llm = FakeLLM(instruct=instruct_json())
    bus = FakeBus()
    pipe = HybridDecisionPipeline(bus, config=CFG, llm_call=llm)
    res = await _run(pipe, market=good_market(price_age_seconds=120.0))
    assert not res.approved
    assert res.block_reason is BlockReason.PRICE_STALE
    assert llm.total_calls == 0
    assert res.llm_called is False


async def test_market_closed_blocks_before_model_call():
    llm = FakeLLM(instruct=instruct_json())
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe, market=good_market(market_open=False))
    assert res.block_reason is BlockReason.MARKET_CLOSED
    assert llm.total_calls == 0


async def test_weak_signal_does_not_call_model():
    llm = FakeLLM(instruct=instruct_json())
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe, signal=strong_signal(confidence_seed=0.3))
    assert res.block_reason is BlockReason.WEAK_SIGNAL
    assert llm.total_calls == 0


# ---------------------------------------------------------------------------
# model output handling
# ---------------------------------------------------------------------------


async def test_malformed_instruct_json_becomes_hold():
    llm = FakeLLM(instruct="this is not json at all")
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe)
    assert not res.approved
    assert res.final_action == "hold"
    assert res.block_reason is BlockReason.MODEL_OUTPUT_INVALID
    assert llm.instruct_calls == 1


async def test_extra_key_in_instruct_json_becomes_hold():
    llm = FakeLLM(instruct=instruct_json(unexpected_field="boom"))
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe)
    assert res.block_reason is BlockReason.MODEL_OUTPUT_INVALID


async def test_low_confidence_buy_is_blocked():
    # confidence 0.5 is below reasoning band → no review → risk blocks.
    llm = FakeLLM(instruct=instruct_json(confidence=0.5))
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe)
    assert not res.approved
    assert res.block_reason is BlockReason.LOW_CONFIDENCE
    assert res.reasoning_called is False


async def test_missing_stop_loss_buy_is_blocked():
    llm = FakeLLM(instruct=instruct_json(suggested_stop_loss=None))
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe)
    assert res.block_reason is BlockReason.MISSING_STOP_LOSS


async def test_low_reward_risk_is_blocked():
    llm = FakeLLM(instruct=instruct_json(suggested_take_profit=101.0, reward_risk_ratio=0.5))
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe)
    assert res.block_reason is BlockReason.REWARD_RISK_TOO_LOW


async def test_duplicate_signal_is_blocked():
    llm = FakeLLM(instruct=instruct_json())
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe, duplicate_signal=True)
    assert res.block_reason is BlockReason.DUPLICATE_SIGNAL


async def test_open_order_is_blocked():
    llm = FakeLLM(instruct=instruct_json())
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe, broker=BrokerState(open_order_exists=True))
    assert res.block_reason is BlockReason.OPEN_ORDER_EXISTS


# ---------------------------------------------------------------------------
# reasoning review — gated, can downgrade
# ---------------------------------------------------------------------------


async def test_reasoning_called_in_gray_zone():
    # confidence 0.7 is inside the 0.55-0.80 band → reasoning runs.
    llm = FakeLLM(instruct=instruct_json(confidence=0.7), reasoning=reasoning_json(confidence=0.8))
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe)
    assert llm.reasoning_calls == 1
    assert res.reasoning_called is True


async def test_reasoning_not_called_for_clear_high_confidence():
    llm = FakeLLM(instruct=instruct_json(confidence=0.95))
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe)
    assert llm.reasoning_calls == 0
    assert res.reasoning_called is False
    assert res.approved is True


async def test_reasoning_downgrade_forces_hold():
    llm = FakeLLM(
        instruct=instruct_json(confidence=0.7),
        reasoning=reasoning_json(
            review_result="downgrade_to_hold", final_model_action="hold", confidence=0.4
        ),
    )
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe)
    assert llm.reasoning_calls == 1
    assert not res.approved
    assert res.block_reason is BlockReason.REASONING_DOWNGRADE


# ---------------------------------------------------------------------------
# approval → deterministic sizing → execution hand-off
# ---------------------------------------------------------------------------


async def test_approved_buy_produces_sized_order():
    llm = FakeLLM(instruct=instruct_json(confidence=0.95))
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe)
    assert res.approved is True
    assert res.order is not None
    assert res.order.qty == 100.0  # deterministic risk-based size, exposure-capped


async def test_qty_zero_blocks_execution():
    llm = FakeLLM(instruct=instruct_json(confidence=0.95))
    pipe = HybridDecisionPipeline(FakeBus(), config=CFG, llm_call=llm)
    res = await _run(pipe, portfolio=flat_portfolio(buying_power=0.0))
    assert not res.approved
    assert res.block_reason is BlockReason.SIZE_ZERO


async def test_execution_published_only_when_approved():
    llm = FakeLLM(instruct=instruct_json(confidence=0.95))
    bus = FakeBus()
    pipe = HybridDecisionPipeline(bus, config=CFG, llm_call=llm, publish_decisions=True)
    res = await _run(pipe)
    assert res.approved
    assert STREAM_DECISIONS in bus.streams()


async def test_no_execution_published_when_blocked():
    llm = FakeLLM(instruct=instruct_json())
    bus = FakeBus()
    pipe = HybridDecisionPipeline(bus, config=CFG, llm_call=llm, publish_decisions=True)
    await _run(pipe, market=good_market(market_open=False))
    assert STREAM_DECISIONS not in bus.streams()


# ---------------------------------------------------------------------------
# ledger / lifecycle events
# ---------------------------------------------------------------------------


async def test_blocked_decision_writes_lifecycle():
    bus = FakeBus()
    pipe = HybridDecisionPipeline(bus, config=CFG, llm_call=FakeLLM(instruct=instruct_json()))
    await _run(pipe, market=good_market(market_open=False))
    assert LifecycleStage.MARKET_VALIDATED.value in bus.stages()
    assert LifecycleStage.RISK_BLOCKED.value in bus.stages()


async def test_approved_decision_writes_lifecycle():
    bus = FakeBus()
    pipe = HybridDecisionPipeline(
        bus, config=CFG, llm_call=FakeLLM(instruct=instruct_json(confidence=0.95))
    )
    await _run(pipe)
    stages = bus.stages()
    assert LifecycleStage.RISK_APPROVED.value in stages
    assert LifecycleStage.ORDER_SIZED.value in stages


async def test_lifecycle_events_carry_identity_envelope():
    bus = FakeBus()
    pipe = HybridDecisionPipeline(
        bus, config=CFG, llm_call=FakeLLM(instruct=instruct_json(confidence=0.95))
    )
    res = await _run(pipe)
    lifecycle = [e for s, e in bus.events if s == STREAM_TRADE_LIFECYCLE]
    assert lifecycle
    for ev in lifecycle:
        assert ev[FieldName.TRACE_ID] == res.trace_id
        assert ev[FieldName.DECISION_ID] == res.decision_id
        assert ev[FieldName.EVENT_VERSION] == "v3"
        assert ev[FieldName.EVENT_TYPE] == HYBRID_LIFECYCLE_EVENT_TYPE


async def test_llm_never_directly_executes():
    # Even if the model insists should_execute=true with a perfect setup, when
    # publish_decisions is off nothing reaches the execution stream, and the
    # validated decision always carries should_execute=False.
    llm = FakeLLM(instruct=instruct_json(confidence=0.95, should_execute=True))
    bus = FakeBus()
    pipe = HybridDecisionPipeline(bus, config=CFG, llm_call=llm)
    res = await _run(pipe)
    assert STREAM_DECISIONS not in bus.streams()
    assert res.instruct is not None
    assert res.instruct.should_execute is False
