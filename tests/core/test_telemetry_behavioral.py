"""Behavioral telemetry — agent_decisions_total + decision-flip rate.

Covers api/telemetry.record_decision: model/action labels, per-symbol flip
detection, and the disabled no-op contract (the reasoning hot path must be
untouched in the default build). Design: docs/platform/telemetry-governance.md §8.5.
"""

from api import telemetry


class _FakeCounter:
    def __init__(self):
        self.calls = []

    def add(self, amount, attributes=None):
        self.calls.append((amount, attributes or {}))


def _install(monkeypatch):
    decisions, flips = _FakeCounter(), _FakeCounter()
    monkeypatch.setattr(telemetry, "_enabled", True)
    monkeypatch.setattr(
        telemetry,
        "_instruments",
        {"agent_decisions": decisions, "agent_decision_flips": flips},
    )
    monkeypatch.setattr(telemetry, "_last_action", {})
    return decisions, flips


class TestRecordDecision:
    def test_records_model_and_action(self, monkeypatch):
        decisions, flips = _install(monkeypatch)
        telemetry.record_decision(symbol="BTC/USD", action="buy", model="gpt")
        assert len(decisions.calls) == 1
        _, attrs = decisions.calls[0]
        assert attrs == {"trading.model": "gpt", "trading.action": "buy"}
        assert flips.calls == []  # no prior action → no flip

    def test_flip_emitted_only_on_change(self, monkeypatch):
        decisions, flips = _install(monkeypatch)
        telemetry.record_decision(symbol="BTC/USD", action="buy", model="gpt")
        telemetry.record_decision(symbol="BTC/USD", action="sell", model="gpt")  # flip
        telemetry.record_decision(symbol="BTC/USD", action="sell", model="gpt")  # no flip
        assert len(decisions.calls) == 3
        assert len(flips.calls) == 1
        _, attrs = flips.calls[0]
        assert attrs == {"trading.symbol": "BTC/USD"}

    def test_per_symbol_flip_isolation(self, monkeypatch):
        _, flips = _install(monkeypatch)
        telemetry.record_decision(symbol="BTC/USD", action="buy", model="gpt")
        telemetry.record_decision(symbol="ETH/USD", action="sell", model="gpt")
        # Different symbols → independent baselines, neither is a flip.
        assert flips.calls == []

    def test_disabled_is_noop(self, monkeypatch):
        # Default _enabled is False; record_decision must not raise or mutate state.
        monkeypatch.setattr(telemetry, "_last_action", {})
        telemetry.record_decision(symbol="BTC/USD", action="buy", model="gpt")
        assert telemetry._last_action == {}
