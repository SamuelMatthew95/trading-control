"""Replay harness + regression validator + promotion gate (Prompt-OS Layer 4).

A challenger version may advance one lifecycle stage ONLY if the deterministic
regression replay passes every hard gate AND the transition is legal. The LLM
cannot influence any of this — it is pure Python math + a state machine.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from api.constants import FieldName, StrategyStatus
from api.main import app
from api.services.promotion_gate import PromotionGate
from api.services.regression_validator import RegressionValidator
from api.services.replay_harness import ReplayHarness, ReplayMetrics
from api.services.strategy_registry import StrategyRegistry


def _trade(pnl: float, pnl_pct: float, *, side: str = "buy", slippage: float = 1.0) -> dict:
    return {
        FieldName.PNL: pnl,
        FieldName.PNL_PERCENT: pnl_pct,
        FieldName.OVERALL_SCORE: 0.6,
        FieldName.SIDE: side,
        FieldName.SLIPPAGE_BPS: slippage,
    }


def _trades(n_win: int, n_loss: int, *, slippage: float = 1.0) -> list[dict]:
    out: list[dict] = []
    for i in range(n_win):
        out.append(_trade(100.0, 1.0 + i * 0.1, slippage=slippage))
    for i in range(n_loss):
        out.append(_trade(-50.0, -1.0 - i * 0.1, slippage=slippage))
    return out


# --------------------------------------------------------------------------- #
# Replay harness
# --------------------------------------------------------------------------- #


def test_replay_harness_computes_core_metrics():
    metrics = ReplayHarness().replay(_trades(9, 3))
    assert metrics.trade_count == 12
    assert metrics.win_rate == pytest.approx(9 / 12, abs=1e-3)
    # 3 losing actionable trades out of 12 → false-positive rate 0.25.
    assert metrics.false_positive_rate == pytest.approx(0.25, abs=1e-3)
    assert metrics.max_drawdown <= 0.0
    assert metrics.avg_slippage_bps == pytest.approx(1.0, abs=1e-6)


def test_replay_harness_empty_is_zeroed():
    metrics = ReplayHarness().replay([])
    assert metrics.trade_count == 0
    assert metrics.win_rate == 0.0


# --------------------------------------------------------------------------- #
# Regression validator (deterministic gates)
# --------------------------------------------------------------------------- #


def test_validator_approves_equal_metrics():
    champ = ReplayMetrics(
        trade_count=20, sharpe_ratio=1.5, max_drawdown=-5.0, false_positive_rate=0.2
    )
    verdict = RegressionValidator().validate(champ, champ)
    assert verdict.approved is True
    assert verdict.reasons == []


def test_validator_rejects_insufficient_sample():
    champ = ReplayMetrics(trade_count=20, sharpe_ratio=1.0)
    cand = ReplayMetrics(trade_count=5, sharpe_ratio=1.0)
    verdict = RegressionValidator().validate(champ, cand)
    assert verdict.approved is False
    assert any("insufficient sample" in r for r in verdict.reasons)


def test_validator_rejects_worse_drawdown():
    champ = ReplayMetrics(trade_count=20, max_drawdown=-5.0)
    cand = ReplayMetrics(trade_count=20, max_drawdown=-8.0)  # 3pp worse > 1pp limit
    verdict = RegressionValidator().validate(champ, cand)
    assert verdict.approved is False
    assert any("drawdown worsened" in r for r in verdict.reasons)


def test_validator_rejects_higher_false_positive():
    champ = ReplayMetrics(trade_count=20, false_positive_rate=0.20)
    cand = ReplayMetrics(trade_count=20, false_positive_rate=0.40)  # +0.20 > 0.05 limit
    verdict = RegressionValidator().validate(champ, cand)
    assert verdict.approved is False
    assert any("false-positive" in r for r in verdict.reasons)


def test_validator_rejects_sharpe_regression():
    champ = ReplayMetrics(trade_count=20, sharpe_ratio=1.5)
    cand = ReplayMetrics(trade_count=20, sharpe_ratio=1.0)  # -0.5 < -0.10 limit
    verdict = RegressionValidator().validate(champ, cand)
    assert verdict.approved is False
    assert any("sharpe regressed" in r for r in verdict.reasons)


# --------------------------------------------------------------------------- #
# Promotion gate (regression + lifecycle)
# --------------------------------------------------------------------------- #


def _gate_with_registered_version(status: StrategyStatus):
    registry = StrategyRegistry()
    sv = registry.register({FieldName.STRATEGY: "challenger-x"})
    # Walk to the requested starting stage one legal step at a time.
    order = [
        StrategyStatus.BACKTESTED,
        StrategyStatus.SHADOW,
        StrategyStatus.CANARY,
        StrategyStatus.LIVE,
    ]
    for stage in order:
        if registry.status(sv.version_id) == status:
            break
        registry.transition(sv.version_id, stage)
    gate = PromotionGate(registry=registry)
    return gate, registry, sv.version_id


def test_promotion_gate_promotes_when_clean():
    gate, registry, vid = _gate_with_registered_version(StrategyStatus.BACKTESTED)
    trades = _trades(9, 3)
    decision = gate.evaluate(
        vid, champion_trades=trades, candidate_trades=trades, to_status=StrategyStatus.SHADOW
    )
    assert decision.approved is True
    assert decision.transitioned is True
    assert registry.status(vid) == StrategyStatus.SHADOW


def test_promotion_gate_blocks_on_regression():
    gate, registry, vid = _gate_with_registered_version(StrategyStatus.BACKTESTED)
    champion = _trades(10, 2)
    candidate = _trades(2, 10)  # far worse: high false-positive rate
    decision = gate.evaluate(
        vid, champion_trades=champion, candidate_trades=candidate, to_status=StrategyStatus.SHADOW
    )
    assert decision.approved is False
    assert decision.transitioned is False
    assert registry.status(vid) == StrategyStatus.BACKTESTED  # unchanged


def test_promotion_gate_blocks_illegal_transition_even_if_metrics_pass():
    gate, registry, vid = _gate_with_registered_version(StrategyStatus.PROPOSED)
    trades = _trades(9, 3)
    # PROPOSED -> LIVE skips stages; metrics pass but the lifecycle must block it.
    decision = gate.evaluate(
        vid, champion_trades=trades, candidate_trades=trades, to_status=StrategyStatus.LIVE
    )
    assert decision.approved is True
    assert decision.transitioned is False
    assert "transition blocked" in decision.reason
    assert registry.status(vid) == StrategyStatus.PROPOSED


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_replay_regression_endpoint():
    transport = ASGITransport(app=app)
    payload = {
        "champion_trades": _trades(9, 3),
        "candidate_trades": _trades(2, 10),
    }
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        resp = await client.post("/learning/replay-regression", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"]["approved"] is False
    assert body["candidate"]["false_positive_rate"] > body["champion"]["false_positive_rate"]
