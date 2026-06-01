"""Unit tests for the deterministic cognitive core: stream, config, agents,
aggregation, decision engine, risk engine, execution engine."""

from __future__ import annotations

import pathlib

from cognitive.agents import (
    MacroAgent,
    MarketView,
    NewsAgent,
    ReasoningAgent,
    RiskAgent,
    TechnicalAgent,
)
from cognitive.aggregation import aggregate
from cognitive.config import DEFAULT_CONFIG, load_config, validate_config_dict
from cognitive.decision import BUY, HOLD, SELL, decide
from cognitive.events import Event, EventStream, EventType
from cognitive.execution import FILLED, SKIPPED, execute
from cognitive.risk import (
    BLOCK_DAILY_LOSS,
    BLOCK_EXPOSURE,
    BLOCK_POSITION_SIZE,
    evaluate_risk,
)

RISING = [100 + i * 0.5 for i in range(80)]
FALLING = [100 - i * 0.5 for i in range(80)]


# --- Event stream ---------------------------------------------------------
def test_event_stream_append_seq_and_latest():
    stream = EventStream()
    stream.emit(EventType.NEWS_SIGNAL, {"sentiment": 0.1}, source="news_agent", ts="t0")
    second = stream.emit(EventType.NEWS_SIGNAL, {"sentiment": 0.2}, source="news_agent", ts="t1")
    assert len(stream) == 2
    assert [e.seq for e in stream] == [0, 1]
    assert stream.latest(EventType.NEWS_SIGNAL) == second
    assert stream.latest(EventType.DECISION) is None


def test_event_stream_subscriber_and_snapshot():
    stream = EventStream()
    seen: list[Event] = []
    stream.subscribe(seen.append)
    stream.emit(EventType.DECISION, {"action": "buy"}, ts="t0")
    assert len(seen) == 1
    snap = stream.snapshot()
    assert snap[0]["type"] == "decision"
    assert snap[0]["seq"] == 0


# --- Config ---------------------------------------------------------------
def test_committed_config_file_is_valid_and_matches_defaults():
    config = load_config()
    assert validate_config_dict(config.to_dict()) == []
    assert config.to_dict() == DEFAULT_CONFIG.to_dict()


def test_load_config_falls_back_on_missing_or_bad(tmp_path: pathlib.Path):
    missing = tmp_path / "nope.json"
    assert load_config(missing).to_dict() == DEFAULT_CONFIG.to_dict()
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json")
    assert load_config(bad).to_dict() == DEFAULT_CONFIG.to_dict()
    out_of_bounds = tmp_path / "oob.json"
    out_of_bounds.write_text('{"weights": {"news": 5, "tech": 0.3, "macro": 0.3}}')
    assert load_config(out_of_bounds).to_dict() == DEFAULT_CONFIG.to_dict()


def test_validate_config_rejects_threshold_inversion():
    data = DEFAULT_CONFIG.to_dict()
    data["buy_threshold"] = 0.1
    data["sell_threshold"] = 0.2  # sell above buy is nonsense
    errors = validate_config_dict(data)
    assert any("sell_threshold" in e for e in errors)


# --- Agents ---------------------------------------------------------------
def test_agents_emit_spec_shaped_payloads():
    market = MarketView("BTC/USD", RISING[-1], RISING, news_sentiment=0.6, news_confidence=0.9)
    stream = EventStream()
    news = NewsAgent().emit(stream, market)
    tech = TechnicalAgent().emit(stream, market)
    macro = MacroAgent().emit(stream, market)
    risk = RiskAgent().emit(stream, market)
    assert news["type"] == "news_signal" and -1 <= news["sentiment"] <= 1
    assert tech["type"] == "tech_signal" and -1 <= tech["trend"] <= 1
    assert macro["type"] == "macro_signal" and -1 <= macro["regime"] <= 1
    assert risk["type"] == "risk_signal" and 0 <= risk["risk_score"] <= 1
    assert isinstance(risk["risk_flags"], list)
    assert len(stream) == 4


def test_technical_agent_is_deterministic_and_directional():
    up = MarketView("X", RISING[-1], RISING)
    down = MarketView("X", FALLING[-1], FALLING)
    assert TechnicalAgent().analyze(up) == TechnicalAgent().analyze(up)
    assert TechnicalAgent().analyze(up)["trend"] > 0
    assert TechnicalAgent().analyze(down)["trend"] < 0


def test_news_agent_neutral_without_external_sentiment():
    market = MarketView("X", RISING[-1], RISING)  # no news_sentiment
    out = NewsAgent().analyze(market)
    assert out["sentiment"] == 0.0 and out["confidence"] == 0.0


def test_injectable_scorer_is_the_llm_seam():
    market = MarketView("X", RISING[-1], RISING)
    agent = TechnicalAgent(scorer=lambda _m: (0.42, 0.99))
    out = agent.analyze(market)
    assert out["trend"] == 0.42 and out["confidence"] == 0.99


def test_reasoning_agent_makes_no_decision():
    out = ReasoningAgent().analyze({"news": 0.5, "tech": 0.3, "macro": 0.1, "risk": 0.2})
    assert out["type"] == "reasoning"
    assert "summary" in out and isinstance(out["summary"], str)
    assert "action" not in out and "decision" not in out


# --- Aggregation ----------------------------------------------------------
def test_aggregate_confidence_weights_news_and_tech():
    features = aggregate(
        {"sentiment": 0.8, "confidence": 0.5},
        {"trend": 1.0, "confidence": 0.5},
        {"regime": 0.4},
        {"risk_score": 0.3},
    )
    assert features["news"] == 0.4  # 0.8 * 0.5
    assert features["tech"] == 0.5  # 1.0 * 0.5
    assert features["macro"] == 0.4  # passthrough
    assert features["risk"] == 0.3  # passthrough


# --- Decision engine (pure math) ------------------------------------------
def test_decision_is_pure_weighted_sum_excluding_risk():
    features = {"news": 1.0, "tech": 1.0, "macro": 1.0, "risk": 1.0}
    decision = decide(features, DEFAULT_CONFIG)
    expected = sum(DEFAULT_CONFIG.weights.values())
    assert decision.score == round(expected, 6)
    assert "risk" not in decision.breakdown  # risk never enters the score
    assert decision.action == BUY


def test_decision_thresholds_buy_sell_hold():
    assert decide({"news": 1.0, "tech": 1.0, "macro": 1.0}, DEFAULT_CONFIG).action == BUY
    assert decide({"news": -1.0, "tech": -1.0, "macro": -1.0}, DEFAULT_CONFIG).action == SELL
    assert decide({"news": 0.0, "tech": 0.0, "macro": 0.0}, DEFAULT_CONFIG).action == HOLD


def test_decision_is_deterministic():
    features = {"news": 0.3, "tech": -0.2, "macro": 0.1}
    assert decide(features, DEFAULT_CONFIG) == decide(features, DEFAULT_CONFIG)


# --- Risk engine (hard rules) ---------------------------------------------
def test_risk_blocks_oversized_position():
    decision = decide({"news": 1.0, "tech": 1.0, "macro": 1.0}, DEFAULT_CONFIG)
    gate = evaluate_risk(decision, config=DEFAULT_CONFIG, requested_position_pct=0.5)
    assert not gate.allowed and BLOCK_POSITION_SIZE in gate.blocks


def test_risk_blocks_exposure_and_daily_loss():
    decision = decide({"news": 1.0, "tech": 1.0, "macro": 1.0}, DEFAULT_CONFIG)
    exposure = evaluate_risk(
        decision, config=DEFAULT_CONFIG, requested_position_pct=0.04, current_exposure_pct=0.5
    )
    assert BLOCK_EXPOSURE in exposure.blocks
    loss = evaluate_risk(
        decision, config=DEFAULT_CONFIG, requested_position_pct=0.01, day_pnl_pct=-0.05
    )
    assert BLOCK_DAILY_LOSS in loss.blocks


def test_risk_allows_clean_trade_and_skips_hold():
    buy = decide({"news": 1.0, "tech": 1.0, "macro": 1.0}, DEFAULT_CONFIG)
    assert evaluate_risk(buy, config=DEFAULT_CONFIG, requested_position_pct=0.03).allowed
    hold = decide({"news": 0.0, "tech": 0.0, "macro": 0.0}, DEFAULT_CONFIG)
    assert not evaluate_risk(hold, config=DEFAULT_CONFIG, requested_position_pct=0.03).allowed


# --- Execution engine (deterministic) -------------------------------------
def test_execution_fills_allowed_and_skips_blocked():
    decision = decide({"news": 1.0, "tech": 1.0, "macro": 1.0}, DEFAULT_CONFIG)
    allowed = evaluate_risk(decision, config=DEFAULT_CONFIG, requested_position_pct=0.04)
    fill = execute(decision, allowed, symbol="X", price=100.0, equity=100_000)
    assert fill.status == FILLED and fill.qty == round(4000 / 100.0, 8)
    blocked = evaluate_risk(decision, config=DEFAULT_CONFIG, requested_position_pct=0.9)
    skip = execute(decision, blocked, symbol="X", price=100.0, equity=100_000)
    assert skip.status == SKIPPED and skip.qty == 0.0
