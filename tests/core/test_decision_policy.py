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


def test_marginal_long_is_rejected_in_risk_off_regime():
    """A long whose score clears buy_threshold but whose confidence sits between
    the default floor and the risk-off floor must HOLD in a bearish regime — the
    book stops chasing weak momentum into a falling market."""
    # confidence 0.30: above default min_confidence (0.20), below RISK_OFF floor (0.35).
    data = {FieldName.DIRECTION: "bullish", FieldName.COMPOSITE_SCORE: 0.30}
    out = decide_policy(data, _ctx(regime=MacroRegime.RISK_OFF))
    assert out[FieldName.ACTION] == AgentAction.HOLD
    assert "risk-off" in out[FieldName.REASONING]


def test_same_marginal_long_buys_outside_risk_off():
    """The exact marginal long that is rejected in risk-off must still BUY in a
    risk-on regime — the gate is regime-conditional, not a blanket tightening."""
    data = {FieldName.DIRECTION: "bullish", FieldName.COMPOSITE_SCORE: 0.30}
    out = decide_policy(data, _ctx(regime=MacroRegime.RISK_ON))
    assert out[FieldName.ACTION] == AgentAction.BUY


def test_strong_long_still_buys_in_risk_off_regime():
    """The entry gate rejects only MARGINAL longs — a high-conviction long that
    clears the risk-off floor still opens (smaller, via the sizing path)."""
    data = {FieldName.DIRECTION: "bullish", FieldName.COMPOSITE_SCORE: 0.85}
    out = decide_policy(data, _ctx(regime=MacroRegime.RISK_OFF))
    assert out[FieldName.ACTION] == AgentAction.BUY


# ---------------------------------------------------------------------------
# Directional bias (proposal #338 — "consider buying instead of selling")
# ---------------------------------------------------------------------------


def test_default_directional_bias_is_neutral_and_omits_factor():
    """The seed params carry bias 0.0 — the score is unchanged and no bias line
    is surfaced, so live behavior is identical until the lean is dialed in."""
    data = {FieldName.DIRECTION: "bullish", FieldName.COMPOSITE_SCORE: 0.75}
    ctx = _ctx(sentiment=0.2, regime=MacroRegime.RISK_ON, imbalance=0.1)
    assert PolicyParams().directional_bias == 0.0
    out = decide_policy(data, ctx)
    assert all("directional_bias" not in f for f in out[FieldName.RISK_FACTORS])


def test_positive_directional_bias_tilts_flat_signal_to_buy():
    """A flat signal (score 0.0) HOLDs by default; a positive lean pushes it past
    the buy threshold. Confidence is sufficient, so only the bias changes the cut."""
    data = {FieldName.COMPOSITE_SCORE: 0.5}  # flat momentum, conviction above floor
    ctx = _ctx()
    neutral = decide_policy(data, ctx, PolicyParams())
    biased = decide_policy(data, ctx, PolicyParams(directional_bias=0.2))
    assert neutral[FieldName.ACTION] == AgentAction.HOLD
    assert biased[FieldName.ACTION] == AgentAction.BUY
    assert any("directional_bias +0.20" in f for f in biased[FieldName.RISK_FACTORS])


def test_negative_directional_bias_tilts_flat_signal_to_sell():
    data = {FieldName.COMPOSITE_SCORE: 0.5}
    biased = decide_policy(data, _ctx(), PolicyParams(directional_bias=-0.2))
    assert biased[FieldName.ACTION] == AgentAction.SELL


def test_directional_bias_is_clamped_into_feature_range():
    """An oversized bias can never push the reported score outside [-1, 1]."""
    data = {FieldName.DIRECTION: "bullish", FieldName.COMPOSITE_SCORE: 0.9}
    out = decide_policy(
        data, _ctx(sentiment=1.0, imbalance=1.0), PolicyParams(directional_bias=5.0)
    )
    score_factor = next(f for f in out[FieldName.RISK_FACTORS] if f.startswith("score "))
    assert float(score_factor.split()[1]) <= 1.0
    assert out[FieldName.ACTION] == AgentAction.BUY


def test_directional_bias_cannot_force_a_trade_below_min_confidence():
    """The bias only tilts the score cut — it must not bypass the conviction
    floor, so a low-confidence signal still HOLDs no matter how large the lean."""
    data = {FieldName.COMPOSITE_SCORE: 0.05}  # below min_confidence (0.20)
    out = decide_policy(data, _ctx(), PolicyParams(directional_bias=0.9))
    assert out[FieldName.ACTION] == AgentAction.HOLD
    assert "insufficient conviction" in out[FieldName.REASONING]


def test_default_params_constant_is_a_policy_params():
    assert isinstance(DEFAULT_POLICY_PARAMS, PolicyParams)


# ---------------------------------------------------------------------------
# Regime directional weighting (proposal #346 — regime_adjustment)
#
# The mechanism EASES (lowers) the BUY score cut in an explicit risk-on (bullish)
# macro regime — the mirror of the risk-off long-gate raises. It is strictly
# entry-side: only the buy cut moves; the SELL cut, the reported score, and every
# RiskGuardian exit are untouched. These tests lock in that the easing is
# risk-on-only, never bypasses conviction, never weakens the risk-off gate, and
# NEVER suppresses a sell.
# ---------------------------------------------------------------------------


# A weak-but-confident long in a risk-on regime: flat momentum, and a bearish
# sentiment (-0.5) offsets the +0.20 risk-on macro term so the blended score
# (0.20·1.0 + 0.20·-0.5 = 0.10) sits BELOW the default 0.15 buy_threshold. Easing
# the cut by 0.10 (to 0.05) is exactly enough to admit it — isolating the
# mechanism under test from the rest of the decision.
_RISK_ON_MARGINAL = {FieldName.COMPOSITE_SCORE: 0.5}


def test_regime_weighting_admits_marginal_long_in_risk_on():
    """In a risk-on regime the marginal long clears the eased BUY cut and BUYs —
    and the eased cut is surfaced for auditability."""
    out = decide_policy(_RISK_ON_MARGINAL, _ctx(regime=MacroRegime.RISK_ON, sentiment=-0.5))
    assert out[FieldName.ACTION] == AgentAction.BUY
    assert any("risk_on_buy_cut" in f for f in out[FieldName.RISK_FACTORS])


def test_regime_weighting_is_a_no_op_outside_risk_on():
    """The easing fires ONLY in risk-on: in a neutral or risk-off regime the same
    marginal long is NOT admitted as a BUY (the looser gate never applies) and no
    eased cut is surfaced, so a non-bullish (or lost) regime keeps the default cut.
    (The risk-off case nets to a SELL on the bearish macro + sentiment; the point
    is that the eased BUY gate is absent — the action is never BUY.)"""
    for regime in (MacroRegime.NEUTRAL, MacroRegime.RISK_OFF):
        out = decide_policy(_RISK_ON_MARGINAL, _ctx(regime=regime, sentiment=-0.5))
        assert out[FieldName.ACTION] != AgentAction.BUY
        assert all("risk_on_buy_cut" not in f for f in out[FieldName.RISK_FACTORS])


def test_regime_weighting_never_suppresses_a_sell_in_risk_on():
    """THE constitution-critical invariant: easing the BUY cut must never block a
    de-risking SELL. A marginal bearish signal whose score sits just past the sell
    cut (-0.18) would be suppressed by a *symmetric* score lean (-0.18 + 0.10 =
    -0.08 → HOLD); because the easing moves ONLY the buy cut, the SELL still fires."""
    # momentum -0.5 + macro +0.2 (risk-on) + sentiment 0.6·0.2=+0.12 → score -0.18,
    # just past the -0.15 sell cut. Confidence 0.6 clears min_confidence.
    data = {FieldName.DIRECTION: "bearish", FieldName.COMPOSITE_SCORE: 0.6}
    out = decide_policy(data, _ctx(regime=MacroRegime.RISK_ON, sentiment=0.6))
    assert out[FieldName.ACTION] == AgentAction.SELL


def test_regime_weighting_never_bypasses_min_confidence():
    """The eased cut only lowers the BUY bar — it must never let a low-conviction
    signal trade, so the conviction floor still rejects it."""
    data = {FieldName.COMPOSITE_SCORE: 0.05}  # below min_confidence (0.20)
    out = decide_policy(data, _ctx(regime=MacroRegime.RISK_ON))
    assert out[FieldName.ACTION] == AgentAction.HOLD
    assert "insufficient conviction" in out[FieldName.REASONING]


def test_regime_weighting_does_not_loosen_risk_off_long_gate():
    """Capital-preservation invariant: the bullish easing must NOT weaken the
    risk-off entry tightening. A marginal long in a risk-off regime is still
    rejected, because the easing never fires outside risk-on."""
    # confidence 0.30: above default floor (0.20), below RISK_OFF floor (0.35).
    data = {FieldName.DIRECTION: "bullish", FieldName.COMPOSITE_SCORE: 0.30}
    out = decide_policy(data, _ctx(regime=MacroRegime.RISK_OFF))
    assert out[FieldName.ACTION] == AgentAction.HOLD
    assert "risk-off" in out[FieldName.REASONING]
