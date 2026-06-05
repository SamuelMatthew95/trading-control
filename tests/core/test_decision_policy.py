"""Tests for the deterministic data-plane decision policy.

The policy is the Level-3 fast path: it must produce real, explainable decisions
from a signal + perception context WITHOUT an LLM, never raise, and stay fully
deterministic so the same inputs always yield the same decision.
"""

from __future__ import annotations

from api.constants import AgentAction, FieldName, MacroRegime
from api.services.decision_policy import (
    DEFAULT_POLICY_PARAMS,
    PolicyParams,
    decide_policy,
)


def _ctx(*, sentiment=0.0, regime=MacroRegime.NEUTRAL, imbalance=0.0) -> dict:
    # Mirror production: fetch_macro_regime stores the regime's STRING value, not
    # the enum member. On Python 3.10 the StrEnum backport's str(member) yields
    # "MacroRegime.RISK_OFF" (not "risk_off"), so passing the member would mis-parse
    # — exactly the 3.10 footgun documented in docs/troubleshooting/market-intel.md.
    regime_value = regime.value if hasattr(regime, "value") else regime
    return {
        FieldName.NEWS_SENTIMENT: {FieldName.SENTIMENT: sentiment},
        FieldName.MACRO_REGIME: {FieldName.REGIME: regime_value},
        FieldName.ORDER_BOOK: {FieldName.IMBALANCE: imbalance},
    }


def test_bullish_confident_signal_buys():
    data = {
        FieldName.DIRECTION: "bullish",
        FieldName.COMPOSITE_SCORE: 0.8,
    }
    out = decide_policy(data, _ctx(sentiment=0.4, regime=MacroRegime.RISK_ON))
    assert out[FieldName.ACTION] == AgentAction.BUY
    assert out[FieldName.CONFIDENCE] == 0.8
    assert out[FieldName.PRIMARY_EDGE] == "policy:deterministic"
    # Every contributing term is reported for auditability.
    assert any("score" in f for f in out[FieldName.RISK_FACTORS])


def test_bearish_confident_signal_sells():
    data = {FieldName.DIRECTION: "bearish", FieldName.COMPOSITE_SCORE: 0.7}
    out = decide_policy(data, _ctx(sentiment=-0.3, regime=MacroRegime.RISK_OFF))
    assert out[FieldName.ACTION] == AgentAction.SELL


def test_low_confidence_holds_even_when_directional():
    data = {FieldName.DIRECTION: "bullish", FieldName.COMPOSITE_SCORE: 0.05}
    out = decide_policy(data, _ctx(regime=MacroRegime.RISK_ON))
    assert out[FieldName.ACTION] == AgentAction.HOLD
    assert "insufficient conviction" in out[FieldName.REASONING]


def test_conflicting_features_net_to_hold():
    # Bullish momentum but bearish sentiment + risk-off macro cancel out.
    data = {FieldName.DIRECTION: "bullish", FieldName.COMPOSITE_SCORE: 0.6}
    out = decide_policy(data, _ctx(sentiment=-1.0, regime=MacroRegime.RISK_OFF))
    assert out[FieldName.ACTION] == AgentAction.HOLD


def test_pct_drives_direction_when_no_explicit_label():
    up = decide_policy({FieldName.PCT: 1.2, FieldName.COMPOSITE_SCORE: 0.9}, _ctx())
    down = decide_policy({FieldName.PCT: -1.2, FieldName.COMPOSITE_SCORE: 0.9}, _ctx())
    assert up[FieldName.ACTION] == AgentAction.BUY
    assert down[FieldName.ACTION] == AgentAction.SELL


def test_is_deterministic():
    data = {FieldName.DIRECTION: "bullish", FieldName.COMPOSITE_SCORE: 0.75}
    ctx = _ctx(sentiment=0.2, regime=MacroRegime.RISK_ON, imbalance=0.1)
    assert decide_policy(data, ctx) == decide_policy(data, ctx)


def test_empty_inputs_never_raise_and_hold():
    out = decide_policy({}, None)
    assert out[FieldName.ACTION] == AgentAction.HOLD
    assert out[FieldName.CONFIDENCE] == 0.0


def test_size_scales_with_confidence_and_has_a_floor():
    strong = decide_policy({FieldName.DIRECTION: "bullish", FieldName.COMPOSITE_SCORE: 1.0}, _ctx())
    weak = decide_policy({FieldName.DIRECTION: "bullish", FieldName.COMPOSITE_SCORE: 0.3}, _ctx())
    assert strong[FieldName.SIZE_PCT] >= weak[FieldName.SIZE_PCT]
    assert weak[FieldName.SIZE_PCT] >= 0.005  # floor


def test_params_are_tunable_thresholds():
    data = {FieldName.DIRECTION: "bullish", FieldName.COMPOSITE_SCORE: 0.6}
    ctx = _ctx()  # only momentum contributes: score = w_momentum = 0.5
    strict = PolicyParams(buy_threshold=0.9)
    lenient = PolicyParams(buy_threshold=0.1)
    assert decide_policy(data, ctx, strict)[FieldName.ACTION] == AgentAction.HOLD
    assert decide_policy(data, ctx, lenient)[FieldName.ACTION] == AgentAction.BUY


def test_default_params_constant_is_a_policy_params():
    assert isinstance(DEFAULT_POLICY_PARAMS, PolicyParams)
