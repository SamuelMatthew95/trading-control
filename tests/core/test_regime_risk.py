"""Unit tests for the regime-aware risk policy (api/services/regime_risk.py).

The policy is the single source of truth for how a risk-off (bearish) macro
regime tightens risk. The core invariant under test: it only ever TIGHTENS in
an explicit risk-off regime and is a no-op (defaults) for every other input, so
a missing/unknown regime can never loosen risk.
"""

from __future__ import annotations

from api.constants import (
    DAILY_LOSS_LIMIT_PCT,
    EXECUTION_DECISION_THRESHOLD,
    RISK_OFF_DAILY_LOSS_LIMIT_PCT,
    RISK_OFF_EXECUTION_DECISION_THRESHOLD,
    RISK_OFF_MIN_CONFIDENCE,
    RISK_OFF_SIZE_MULTIPLIER,
    RISK_OFF_STOP_LOSS_PCT,
    RISK_OFF_TAKE_PROFIT_PCT,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    MacroRegime,
)
from api.services import regime_risk


def test_risk_off_constants_are_strictly_more_conservative():
    """Every risk-off parameter must be strictly tighter than its default — a
    looser risk-off value would make a bearish regime RISKIER, the opposite of
    the intent. This invariant guards future constant edits."""
    assert RISK_OFF_STOP_LOSS_PCT < STOP_LOSS_PCT
    assert RISK_OFF_TAKE_PROFIT_PCT < TAKE_PROFIT_PCT
    assert RISK_OFF_DAILY_LOSS_LIMIT_PCT < DAILY_LOSS_LIMIT_PCT
    assert 0.0 < RISK_OFF_SIZE_MULTIPLIER < 1.0
    # A tighter EXECUTION gate means a HIGHER bar — must exceed the default.
    assert RISK_OFF_EXECUTION_DECISION_THRESHOLD > EXECUTION_DECISION_THRESHOLD


def test_regime_of_extracts_value_and_fails_safe_on_garbage():
    assert regime_risk.regime_of({"regime": "risk_off"}) == MacroRegime.RISK_OFF
    assert regime_risk.regime_of({}) is None
    assert regime_risk.regime_of(None) is None
    # Non-dict payloads (mocked / malformed tool results) must not raise.
    assert regime_risk.regime_of(0) is None
    assert regime_risk.regime_of("risk_off") is None
    assert regime_risk.regime_of([1, 2]) is None


def test_is_risk_off():
    assert regime_risk.is_risk_off(MacroRegime.RISK_OFF) is True
    assert regime_risk.is_risk_off(MacroRegime.RISK_ON) is False
    assert regime_risk.is_risk_off(MacroRegime.NEUTRAL) is False
    assert regime_risk.is_risk_off(None) is False


def test_stop_loss_tightens_only_for_long_in_risk_off():
    assert regime_risk.stop_loss_pct(MacroRegime.RISK_OFF, is_long=True) == RISK_OFF_STOP_LOSS_PCT
    assert regime_risk.stop_loss_pct(MacroRegime.RISK_OFF, is_long=False) == STOP_LOSS_PCT
    assert regime_risk.stop_loss_pct(MacroRegime.RISK_ON, is_long=True) == STOP_LOSS_PCT
    assert regime_risk.stop_loss_pct(None, is_long=True) == STOP_LOSS_PCT


def test_take_profit_tightens_only_for_long_in_risk_off():
    assert (
        regime_risk.take_profit_pct(MacroRegime.RISK_OFF, is_long=True) == RISK_OFF_TAKE_PROFIT_PCT
    )
    assert regime_risk.take_profit_pct(MacroRegime.RISK_OFF, is_long=False) == TAKE_PROFIT_PCT
    assert regime_risk.take_profit_pct(MacroRegime.NEUTRAL, is_long=True) == TAKE_PROFIT_PCT


def test_daily_loss_limit_tightens_in_risk_off():
    assert regime_risk.daily_loss_limit_pct(MacroRegime.RISK_OFF) == RISK_OFF_DAILY_LOSS_LIMIT_PCT
    assert regime_risk.daily_loss_limit_pct(MacroRegime.RISK_ON) == DAILY_LOSS_LIMIT_PCT
    assert regime_risk.daily_loss_limit_pct(None) == DAILY_LOSS_LIMIT_PCT


def test_size_multiplier_shrinks_only_long_in_risk_off():
    assert (
        regime_risk.size_multiplier(MacroRegime.RISK_OFF, is_long=True) == RISK_OFF_SIZE_MULTIPLIER
    )
    assert regime_risk.size_multiplier(MacroRegime.RISK_OFF, is_long=False) == 1.0
    assert regime_risk.size_multiplier(MacroRegime.RISK_ON, is_long=True) == 1.0
    assert regime_risk.size_multiplier(None, is_long=True) == 1.0


def test_min_confidence_raises_only_for_long_in_risk_off():
    default = 0.20
    # Long in risk-off: bar is raised to the risk-off floor.
    assert (
        regime_risk.min_confidence(MacroRegime.RISK_OFF, default, is_long=True)
        == RISK_OFF_MIN_CONFIDENCE
    )
    # Shorts in risk-off keep the default — a bearish tape is favourable to them.
    assert regime_risk.min_confidence(MacroRegime.RISK_OFF, default, is_long=False) == default
    # Long in a non-risk-off regime keeps the default.
    assert regime_risk.min_confidence(MacroRegime.RISK_ON, default, is_long=True) == default
    assert regime_risk.min_confidence(None, default, is_long=True) == default


def test_min_confidence_never_lowers_a_stricter_default():
    """The floor can only ever RAISE the bar — an operator/control-plane default
    already above the risk-off floor must survive (max semantics)."""
    stricter = RISK_OFF_MIN_CONFIDENCE + 0.10
    assert regime_risk.min_confidence(MacroRegime.RISK_OFF, stricter, is_long=True) == stricter


def test_risk_off_min_confidence_exceeds_default_seed():
    """The risk-off floor must be strictly stricter than the seed policy floor,
    or the entry gate is a no-op."""
    from api.services.decision_policy import DEFAULT_POLICY_PARAMS

    assert RISK_OFF_MIN_CONFIDENCE > DEFAULT_POLICY_PARAMS.min_confidence


def test_execution_threshold_raises_only_for_long_in_risk_off():
    default = EXECUTION_DECISION_THRESHOLD
    # Long in risk-off: the gate is raised to the risk-off bar.
    assert (
        regime_risk.execution_threshold(MacroRegime.RISK_OFF, default, is_long=True)
        == RISK_OFF_EXECUTION_DECISION_THRESHOLD
    )
    # SELL exits keep the default so the book can always de-risk.
    assert regime_risk.execution_threshold(MacroRegime.RISK_OFF, default, is_long=False) == default
    # A long in a non-risk-off regime keeps the default gate.
    assert regime_risk.execution_threshold(MacroRegime.RISK_ON, default, is_long=True) == default
    assert regime_risk.execution_threshold(MacroRegime.NEUTRAL, default, is_long=True) == default
    assert regime_risk.execution_threshold(None, default, is_long=True) == default


def test_execution_threshold_never_lowers_a_stricter_default():
    """The gate can only ever RAISE the bar — a control-plane override already
    above the risk-off bar (e.g. a hand-tuned memory-mode threshold) survives."""
    stricter = RISK_OFF_EXECUTION_DECISION_THRESHOLD + 0.10
    assert regime_risk.execution_threshold(MacroRegime.RISK_OFF, stricter, is_long=True) == stricter


def test_fail_safe_unknown_regime_never_tightens():
    """A garbage/unrecognised regime string must yield defaults — never tighten."""
    assert regime_risk.stop_loss_pct("garbage", is_long=True) == STOP_LOSS_PCT
    assert regime_risk.take_profit_pct("garbage", is_long=True) == TAKE_PROFIT_PCT
    assert regime_risk.daily_loss_limit_pct("garbage") == DAILY_LOSS_LIMIT_PCT
    assert regime_risk.size_multiplier("garbage", is_long=True) == 1.0
    assert regime_risk.min_confidence("garbage", 0.20, is_long=True) == 0.20
    assert (
        regime_risk.execution_threshold("garbage", EXECUTION_DECISION_THRESHOLD, is_long=True)
        == EXECUTION_DECISION_THRESHOLD
    )
