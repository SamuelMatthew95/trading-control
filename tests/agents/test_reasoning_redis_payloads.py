"""Pure-function tests for ReasoningAgent's Redis payload builders.

These cover the price formatting, action filtering and fallback flag logic
without spinning up a Redis client or a real agent — failures point straight
at the builder, not at integration glue.
"""

from __future__ import annotations

from api.constants import AgentAction, FieldName
from api.services.agents.reasoning_agent import ReasoningAgent


def test_build_decision_payload_uses_price_when_present() -> None:
    payload = ReasoningAgent._build_decision_payload(
        data={FieldName.SYMBOL: "BTC/USD", FieldName.PRICE: 67000.5},
        summary={FieldName.CONFIDENCE: 0.8, FieldName.PRIMARY_EDGE: "momentum"},
        trace_id="t-1",
        action=AgentAction.BUY,
        is_fallback=False,
    )
    assert payload[FieldName.SYMBOL] == "BTC/USD"
    assert payload[FieldName.PRICE] == 67000.5
    assert payload[FieldName.ACTION] == AgentAction.BUY
    assert payload[FieldName.CONFIDENCE] == 0.8
    assert payload["reasoning_summary"] == "momentum"
    assert payload["llm_succeeded"] is True
    assert payload[FieldName.TRACE_ID] == "t-1"


def test_build_decision_payload_falls_back_to_last_price() -> None:
    payload = ReasoningAgent._build_decision_payload(
        data={FieldName.SYMBOL: "BTC/USD", FieldName.LAST_PRICE: 65000.0},
        summary={FieldName.CONFIDENCE: 0.5},
        trace_id="t-2",
        action=AgentAction.SELL,
        is_fallback=False,
    )
    assert payload[FieldName.PRICE] == 65000.0


def test_build_decision_payload_marks_fallback_as_llm_failed() -> None:
    payload = ReasoningAgent._build_decision_payload(
        data={FieldName.SYMBOL: "BTC/USD"},
        summary={},
        trace_id="t-3",
        action=AgentAction.HOLD,
        is_fallback=True,
    )
    assert payload["llm_succeeded"] is False
    assert payload[FieldName.CONFIDENCE] == 0.0
    assert payload["reasoning_summary"] == ""


def test_build_decision_payload_handles_missing_symbol() -> None:
    payload = ReasoningAgent._build_decision_payload(
        data={},
        summary={},
        trace_id="t-4",
        action=AgentAction.HOLD,
        is_fallback=False,
    )
    # Empty string is fine — the frontend handles it as "--"
    assert payload[FieldName.SYMBOL] == ""


def test_build_decision_notification_includes_formatted_price() -> None:
    notif = ReasoningAgent._build_decision_notification(
        action=AgentAction.BUY,
        symbol="BTC/USD",
        price=67450.5,
        trace_id="t-5",
        is_fallback=False,
    )
    assert notif[FieldName.TYPE] == "trade_signal"
    assert notif["title"] == "BUY signal — BTC/USD"
    assert "at $67,450.50" in notif["body"]
    assert notif["severity"] == "info"
    assert notif[FieldName.ACTION] == AgentAction.BUY
    assert notif[FieldName.SYMBOL] == "BTC/USD"
    assert notif[FieldName.TRACE_ID] == "t-5"


def test_build_decision_notification_omits_price_when_absent() -> None:
    notif = ReasoningAgent._build_decision_notification(
        action=AgentAction.SELL,
        symbol="ETH/USD",
        price=None,
        trace_id="t-6",
        is_fallback=False,
    )
    assert " at $" not in notif["body"]
    assert notif["body"] == "Reasoning agent decided to sell ETH/USD"


def test_build_decision_notification_omits_price_when_zero() -> None:
    # Zero is technically a valid float but uninformative — should be skipped.
    notif = ReasoningAgent._build_decision_notification(
        action=AgentAction.BUY,
        symbol="BTC/USD",
        price=0,
        trace_id="t-7",
        is_fallback=False,
    )
    assert " at $" not in notif["body"]


def test_build_decision_notification_omits_price_when_non_numeric() -> None:
    notif = ReasoningAgent._build_decision_notification(
        action=AgentAction.BUY,
        symbol="BTC/USD",
        price="not-a-number",  # surfaced from a malformed upstream payload
        trace_id="t-8",
        is_fallback=False,
    )
    assert " at $" not in notif["body"]


def test_build_decision_notification_fallback_buy_suppressed() -> None:
    notif = ReasoningAgent._build_decision_notification(
        action=AgentAction.BUY,
        symbol="BTC/USD",
        price=67450.5,
        trace_id="t-9",
        is_fallback=True,
        reason="fallback_detected",
    )
    assert notif["title"] == "Fallback BUY suppressed — BTC/USD"
    assert notif["severity"] == "warning"
    assert notif["type"] == "fallback_trade_blocked"
    assert notif["original_action"] == AgentAction.BUY
    assert notif["action"] == AgentAction.HOLD
    assert notif["llm_succeeded"] is False


def test_actionable_set_matches_agent_action_constants() -> None:
    assert ReasoningAgent._ACTIONABLE_ACTIONS == frozenset({AgentAction.BUY, AgentAction.SELL})
