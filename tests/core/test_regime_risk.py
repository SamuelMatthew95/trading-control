"""Unit tests for the regime-aware risk policy (api/services/regime_risk.py).

The policy is the single source of truth for how a risk-off (bearish) macro
regime tightens risk. The core invariant under test: it only ever TIGHTENS in
an explicit risk-off regime and is a no-op (defaults) for every other input, so
a missing/unknown regime can never loosen risk.
"""

from __future__ import annotations

from api.constants import (
    DAILY_LOSS_LIMIT_PCT,
    RISK_OFF_DAILY_LOSS_LIMIT_PCT,
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


def test_fail_safe_unknown_regime_never_tightens():
    """A garbage/unrecognised regime string must yield defaults — never tighten."""
    assert regime_risk.stop_loss_pct("garbage", is_long=True) == STOP_LOSS_PCT
    assert regime_risk.take_profit_pct("garbage", is_long=True) == TAKE_PROFIT_PCT
    assert regime_risk.daily_loss_limit_pct("garbage") == DAILY_LOSS_LIMIT_PCT
    assert regime_risk.size_multiplier("garbage", is_long=True) == 1.0
