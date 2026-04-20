from __future__ import annotations

from api.services.multi_agent_orchestrator import MultiAgentOrchestrator


def test_analyze_trade_retries_on_low_confidence(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    orchestrator = MultiAgentOrchestrator(api_key=None)

    calls = {"count": 0}

    def fake_once(asset: str, timeframe: str, portfolio_state: dict):
        calls["count"] += 1
        if calls["count"] == 1:
            return (
                {
                    "DECISION": "FLAT",
                    "ASSET": asset,
                    "SIZE": "0 units",
                    "ENTRY": "0.00",
                    "STOP": "0.00",
                    "TARGET": "0.00",
                    "R/R RATIO": "0.0:1",
                    "CONFIDENCE": "LOW",
                    "SIGNAL SUMMARY": [],
                    "RISK FLAGS": ["LOW_CONSENSUS"],
                    "RATIONALE": "needs more context",
                    "INVALIDATION": "N/A",
                },
                [],
                [],
            )
        return (
            {
                "DECISION": "LONG",
                "ASSET": asset,
                "SIZE": "10 units",
                "ENTRY": "100.00",
                "STOP": "95.00",
                "TARGET": "110.00",
                "R/R RATIO": "2.0:1",
                "CONFIDENCE": "MEDIUM",
                "SIGNAL SUMMARY": [],
                "RISK FLAGS": [],
                "RATIONALE": "improved on second pass",
                "INVALIDATION": "Below stop",
            },
            [],
            [],
        )

    monkeypatch.setattr(orchestrator, "_analyze_trade_once", fake_once)

    decision = orchestrator.analyze_trade("AAPL", "1D", {"total_value": 100000}, max_iterations=2)

    assert calls["count"] == 2
    assert decision["DECISION"] == "LONG"
    assert decision["LOOP_ITERATION"] == 2
    assert decision["LOOP_COMPLETED"] is True


def test_analyze_trade_stops_when_system_error(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    orchestrator = MultiAgentOrchestrator(api_key=None)

    def fake_once(asset: str, timeframe: str, portfolio_state: dict):
        return (
            {
                "DECISION": "FLAT",
                "ASSET": asset,
                "SIZE": "0 units",
                "ENTRY": "0.00",
                "STOP": "0.00",
                "TARGET": "0.00",
                "R/R RATIO": "0.0:1",
                "CONFIDENCE": "LOW",
                "SIGNAL SUMMARY": [f"error for {asset} {timeframe}"],
                "RISK FLAGS": ["SYSTEM_ERROR"],
                "RATIONALE": "tool call failed",
                "INVALIDATION": "N/A",
            },
            ["step_failure"],
            [],
        )

    monkeypatch.setattr(orchestrator, "_analyze_trade_once", fake_once)

    decision = orchestrator.analyze_trade("MSFT", "1D", {"total_value": 100000}, max_iterations=3)

    assert decision["LOOP_ITERATION"] == 1
    assert decision["RISK FLAGS"] == ["SYSTEM_ERROR", "step_failure"]


def test_next_timeframe_progression(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    orchestrator = MultiAgentOrchestrator(api_key=None)

    assert orchestrator._next_timeframe("1W") == "1D"
    assert orchestrator._next_timeframe("1D") == "4H"
    assert orchestrator._next_timeframe("4H") == "1H"
    assert orchestrator._next_timeframe("1H") == "1D"
    assert orchestrator._next_timeframe("UNKNOWN") == "1D"


def test_should_retry_logic_matrix(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    orchestrator = MultiAgentOrchestrator(api_key=None)

    assert (
        orchestrator._should_retry(
            {"RISK FLAGS": ["SYSTEM_ERROR"], "CONFIDENCE": "LOW"},
            [],
            [],
            iteration=1,
            max_iterations=3,
        )
        is False
    )
    assert (
        orchestrator._should_retry(
            {"RISK FLAGS": [], "CONFIDENCE": "HIGH"},
            ["step_failure"],
            [],
            iteration=1,
            max_iterations=3,
        )
        is True
    )
    assert (
        orchestrator._should_retry(
            {"RISK FLAGS": ["LOW_CONSENSUS"], "CONFIDENCE": "LOW"},
            [],
            [],
            iteration=1,
            max_iterations=3,
        )
        is True
    )
    assert (
        orchestrator._should_retry(
            {"RISK FLAGS": [], "CONFIDENCE": "LOW"},
            [],
            [],
            iteration=3,
            max_iterations=3,
        )
        is False
    )


def test_analyze_trade_uses_real_single_pass_and_timeframe_shift(monkeypatch, tmp_path):
    """Exercise the real _analyze_trade_once flow while stubbing only tool/model execution."""
    monkeypatch.chdir(tmp_path)
    orchestrator = MultiAgentOrchestrator(api_key=None)
    seen_timeframes: list[str] = []

    def fake_run_step(step, context):
        seen_timeframes.append(context["timeframe"])
        if step.name == "signal":
            return [{"direction": "LONG", "confidence": 0.8}]
        if step.name == "consensus":
            if context["timeframe"] == "1D":
                return {"direction": "FLAT", "agreement_ratio": 0.4, "signal_strength": 0.4}
            return {"direction": "LONG", "agreement_ratio": 0.8, "signal_strength": 0.7}
        if step.name == "risk":
            return {"veto": False, "flags": []}
        if step.name == "sizing":
            return {"units": 12, "entry": 100.0, "stop": 95.0, "target": 110.0, "rr_ratio": 2.0}
        if step.name == "decision":
            signal_strength = float(context["consensus"].get("signal_strength", 0))
            confidence = (
                "HIGH" if signal_strength > 0.8 else "MEDIUM" if signal_strength > 0.6 else "LOW"
            )
            return {
                "DECISION": context["consensus"].get("direction", "FLAT"),
                "ASSET": context["asset"],
                "SIZE": "12 units",
                "ENTRY": "100.00",
                "STOP": "95.00",
                "TARGET": "110.00",
                "R/R RATIO": "2.0:1",
                "CONFIDENCE": confidence,
                "SIGNAL SUMMARY": [],
                "RISK FLAGS": context["risk"].get("flags", []),
                "RATIONALE": "test decision",
                "INVALIDATION": "Below stop",
            }
        raise AssertionError(f"unexpected step {step.name}")

    monkeypatch.setattr(orchestrator.executor, "run_step", fake_run_step)

    decision = orchestrator.analyze_trade(
        "AAPL",
        "1D",
        {"total_value": 100000, "drawdown": -0.02},
        max_iterations=2,
    )

    assert decision["DECISION"] == "LONG"
    assert decision["LOOP_ITERATION"] == 2
    assert "1D" in seen_timeframes
    assert "4H" in seen_timeframes
