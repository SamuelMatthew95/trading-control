"""Tests for decision counterfactuals and drift detection."""

from __future__ import annotations

from cognitive.agents import MarketView
from cognitive.counterfactual import counterfactual
from cognitive.drift import DriftMonitor
from cognitive.events import EventType
from cognitive.loop import CognitiveLoop


# --- Counterfactuals ------------------------------------------------------
def test_counterfactual_long_win_is_its_own_best_action():
    result = counterfactual("buy", realized_pnl_pct=2.0, side="buy")
    assert result.chosen_pnl_pct == 2.0
    assert result.alternatives == {"buy": 2.0, "sell": -2.0, "hold": 0.0}
    assert result.best_action == "buy"
    assert result.regret_pct == 0.0
    assert result.was_best is True


def test_counterfactual_long_loss_regrets_the_short():
    result = counterfactual("buy", realized_pnl_pct=-1.5, side="buy")
    # chosen long lost 1.5; the short would have made +1.5 -> regret 3.0
    assert result.best_action == "sell"
    assert result.best_pnl_pct == 1.5
    assert result.regret_pct == 3.0
    assert result.was_best is False


def test_counterfactual_short_win_recovers_move_sign():
    # a profitable short: realized pnl +2 means the price fell 2 -> short was best
    result = counterfactual("sell", realized_pnl_pct=2.0, side="sell")
    assert result.chosen_pnl_pct == 2.0
    assert result.best_action == "sell"
    assert result.regret_pct == 0.0


# --- Drift monitor --------------------------------------------------------
def test_drift_flags_a_degrading_higher_is_better_metric():
    monitor = DriftMonitor(window=20, min_samples=10)
    monitor.register("score", higher_is_better=True, threshold=8.0)
    for _ in range(10):
        monitor.observe("score", 90.0)
    for _ in range(10):
        monitor.observe("score", 70.0)
    alerts = monitor.assess()
    assert len(alerts) == 1
    assert alerts[0].metric == "score" and alerts[0].direction == "down"
    assert alerts[0].delta == 20.0


def test_drift_flags_a_rising_lower_is_better_metric_and_ignores_stable():
    monitor = DriftMonitor(window=20, min_samples=10)
    monitor.register("regret", higher_is_better=False, threshold=0.5)
    monitor.register("stable", higher_is_better=True, threshold=8.0)
    for _ in range(10):
        monitor.observe("regret", 0.1)
        monitor.observe("stable", 80.0)
    for _ in range(10):
        monitor.observe("regret", 2.0)
        monitor.observe("stable", 80.0)
    alerts = {a.metric: a for a in monitor.assess()}
    assert "regret" in alerts and alerts["regret"].direction == "up"
    assert "stable" not in alerts  # flat metric does not drift


# --- Loop integration -----------------------------------------------------
def _close(loop: CognitiveLoop, trace_id: str, *, pnl_pct: float, adverse: float, slip: float):
    market = MarketView("NVDA", 105.0, [100 + j * 0.2 for j in range(70)])
    loop.step(market, equity=100_000, position_pct=0.03, trace_id=trace_id)
    loop.close_trade(
        trace_id,
        realized_pnl=pnl_pct * 100,
        realized_pnl_pct=pnl_pct,
        max_adverse_pct=adverse,
        slippage_bps=slip,
        side="buy",
        entry_price=105.0,
        window_low=100.0,
        window_high=110.0,
    )


def test_loop_emits_counterfactual_and_surfaces_regret():
    loop = CognitiveLoop()
    _close(loop, "t1", pnl_pct=1.5, adverse=0.3, slip=1.0)
    assert loop.stream.latest(EventType.COUNTERFACTUAL) is not None
    snap = loop.snapshot()
    assert snap["counterfactuals"]
    assert "mean_regret_pct" in snap["learning"]
    assert "drift" in snap and "monitor" in snap["drift"]


def test_loop_detects_drift_when_trade_quality_collapses():
    loop = CognitiveLoop()
    for i in range(16):
        _close(loop, f"good-{i}", pnl_pct=2.5, adverse=0.3, slip=0.5)
    for i in range(16):
        _close(loop, f"bad-{i}", pnl_pct=-2.5, adverse=3.0, slip=9.0)
    alerts = loop.detect_drift()
    assert alerts  # quality / hit-rate / regret degraded across the window
    assert loop.stream.latest(EventType.DRIFT) is not None
