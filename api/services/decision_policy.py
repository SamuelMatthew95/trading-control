"""Deterministic data-plane decision policy — the fast path that does not need an LLM.

Level-3 architecture (data plane / control plane split): the per-signal trading
decision must be FAST, deterministic and ALWAYS AVAILABLE — it cannot hang off a
slow, rate-limited, non-deterministic external LLM on the critical path. This
module is that fast path.

Given the same signal context the LLM sees (composite score, momentum direction,
live market-intel perception) plus a set of tunable :class:`PolicyParams`, it
returns a real, explainable decision — no IO, no network, no LLM. Pure and
trivially unit-testable.

The LLM's job moves to the CONTROL PLANE: instead of making every tick decision,
it periodically deliberates and updates ``PolicyParams`` (and the adaptive
directive). While the LLM is degraded the policy keeps trading on the last good
params, so the downstream learning loop never starves — the pipeline stays live
by construction rather than failing closed on every signal.

Scoring is a transparent weighted blend of directional features in [-1, 1]:
  momentum (signal direction / bar move) · news sentiment · macro regime ·
  order-book imbalance
Confidence is the signal's own composite score. The decision is a threshold cut
on the blended score, gated by a minimum confidence — every term is reported in
``risk_factors`` so the rationale is auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api.config import settings
from api.constants import AgentAction, FieldName, MacroRegime
from api.services import regime_risk


@dataclass(frozen=True)
class PolicyParams:
    """Tunable knobs for the deterministic policy — the control plane's output.

    These are what the LLM (or an operator) adjusts on the slow loop; the data
    plane just executes them. Kept as a frozen dataclass so a params set is an
    immutable, versionable value, mirroring how the adaptive directive is stored.
    """

    buy_threshold: float = 0.15  # blended score at/above which we go long
    sell_threshold: float = 0.15  # blended score at/below -this which we go short
    min_confidence: float = 0.20  # composite score required to act at all
    w_momentum: float = 0.50  # weight on signal direction / bar move
    w_sentiment: float = 0.20  # weight on news sentiment
    w_macro: float = 0.20  # weight on macro risk-on/off regime
    w_imbalance: float = 0.10  # weight on order-book size imbalance
    base_size_pct: float = 0.02  # position size as a fraction of portfolio
    stop_atr_x: float = 1.5  # ATR-multiple stop distance
    rr_ratio: float = 2.0  # reward:risk target
    # Additive tilt applied to the blended score, clamped into [-1, 1]: >0 leans
    # the cut toward BUY, <0 toward SELL. Default 0.0 = neutral (no behavior
    # change). This is the safe, bounded expression of proposal #338 ("consider
    # buying instead of selling") — a directional LEAN the control plane can dial
    # in, NOT a literal inversion of the signal's own direction (which would
    # defeat momentum and the risk hierarchy). Tuned via set_policy_params.
    directional_bias: float = 0.0


# The seed params the data plane runs until the control plane evolves them.
DEFAULT_POLICY_PARAMS = PolicyParams()

# Active params for the data plane. The control plane (LLM deliberation on the
# slow loop) replaces this via set_policy_params(); the hot path only ever reads
# it through get_policy_params(). This is the seam Step 3 wires to Redis so an
# evolved param set survives a restart, mirroring the adaptive-directive store.
_active_policy_params: PolicyParams = DEFAULT_POLICY_PARAMS


def get_policy_params() -> PolicyParams:
    """The params the data plane currently decides with (seed until evolved)."""
    return _active_policy_params


def set_policy_params(params: PolicyParams | None) -> None:
    """Install a new param set (control plane); ``None`` resets to the seed."""
    global _active_policy_params
    _active_policy_params = params or DEFAULT_POLICY_PARAMS


def _direction_sign(data: dict[str, Any]) -> tuple[float, str]:
    """Momentum direction in {-1, 0, +1} from the signal's direction/action/move."""
    raw = str(
        data.get(FieldName.DIRECTION)
        or data.get(FieldName.SIGNAL)
        or data.get(FieldName.ACTION)
        or ""
    ).lower()
    if raw in {"bullish", AgentAction.BUY, "long"}:
        return 1.0, raw
    if raw in {"bearish", AgentAction.SELL, "short"}:
        return -1.0, raw
    pct = float(data.get(FieldName.PCT) or 0.0)
    if pct > 0:
        return 1.0, f"pct {pct:+.2f}%"
    if pct < 0:
        return -1.0, f"pct {pct:+.2f}%"
    return 0.0, "flat"


def _macro_sign(context: dict[str, Any]) -> float:
    """Macro regime as a directional bias in {-1, 0, +1}."""
    macro = context.get(FieldName.MACRO_REGIME) or {}
    regime = str(macro.get(FieldName.REGIME) or "").lower()
    if regime == MacroRegime.RISK_ON:
        return 1.0
    if regime == MacroRegime.RISK_OFF:
        return -1.0
    return 0.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def decide_policy(
    data: dict[str, Any],
    context: dict[str, Any] | None = None,
    params: PolicyParams = DEFAULT_POLICY_PARAMS,
) -> dict[str, Any]:
    """Produce a deterministic trading decision from a signal + perception context.

    Returns the same summary shape the LLM path emits (action / confidence /
    primary_edge / reasoning / risk_factors / size / stop / rr), so it is a
    drop-in decision for the reasoning node. Never raises: malformed inputs
    degrade to a HOLD with an explanatory rationale.
    """
    context = context or {}

    momentum, momentum_label = _direction_sign(data)
    news = context.get(FieldName.NEWS_SENTIMENT) or {}
    sentiment = _clamp(float(news.get(FieldName.SENTIMENT) or 0.0), -1.0, 1.0)
    macro = _macro_sign(context)
    book = context.get(FieldName.ORDER_BOOK) or {}
    imbalance = _clamp(float(book.get(FieldName.IMBALANCE) or 0.0), -1.0, 1.0)
    confidence = _clamp(float(data.get(FieldName.COMPOSITE_SCORE) or 0.0), 0.0, 1.0)

    blended = (
        params.w_momentum * momentum
        + params.w_sentiment * sentiment
        + params.w_macro * macro
        + params.w_imbalance * imbalance
    )
    # Apply the control-plane directional lean (proposal #338; default 0.0 = no-op)
    # and clamp back into the feature range so a large bias can never push the
    # score outside [-1, 1]. The reported score is the genuine blended signal — the
    # regime weighting below moves the BUY *cut*, never the score itself.
    score = round(_clamp(blended + params.directional_bias, -1.0, 1.0), 4)

    regime = regime_risk.regime_of(context.get(FieldName.MACRO_REGIME))

    # Regime directional weighting (proposal #346, default OFF): the risk-ON mirror
    # of the risk-off long-gate raise below. In an explicit risk-on regime the BUY
    # cut a new long must clear is EASED (lowered) so a confirmed bullish tape
    # admits marginal longs sooner. Resolved through regime_risk so it eases ONLY
    # in risk-on with the flag on, and ONLY the buy cut — the SELL cut
    # (params.sell_threshold) is untouched, so easing can never suppress a sell.
    buy_cut = regime_risk.buy_threshold(
        regime,
        params.buy_threshold,
        enabled=settings.REGIME_DIRECTIONAL_WEIGHTING_ENABLED,
    )

    # Every contributing term is surfaced so the decision is auditable, not opaque.
    risk_factors = [
        f"momentum {momentum:+.0f} ({momentum_label})",
        f"sentiment {sentiment:+.2f}",
        f"macro {macro:+.0f}",
        f"imbalance {imbalance:+.2f}",
        f"score {score:+.3f}",
        f"confidence {confidence:.2f}",
    ]
    if params.directional_bias:
        risk_factors.append(f"directional_bias {params.directional_bias:+.2f}")
    if buy_cut != params.buy_threshold:
        risk_factors.append(f"risk_on_buy_cut {buy_cut:+.2f}")

    # A risk-off (bearish) regime raises the conviction bar a NEW long must clear
    # to open — marginal longs are rejected (HOLD), not chased into a falling
    # market. Resolved through regime_risk so it can only ever tighten; shorts and
    # every other regime keep params.min_confidence.
    long_floor = regime_risk.min_confidence(
        regime,
        params.min_confidence,
        is_long=True,
    )

    if confidence < params.min_confidence:
        action = AgentAction.HOLD
        why = f"confidence {confidence:.2f} < {params.min_confidence:.2f} — insufficient conviction"
    elif score >= buy_cut and confidence < long_floor:
        action = AgentAction.HOLD
        why = (
            f"risk-off regime: long confidence {confidence:.2f} < {long_floor:.2f} "
            f"— marginal long rejected in a bearish market"
        )
    elif score >= buy_cut:
        action = AgentAction.BUY
        why = f"score {score:+.3f} ≥ buy_threshold {buy_cut:+.2f}"
    elif score <= -params.sell_threshold:
        action = AgentAction.SELL
        why = f"score {score:+.3f} ≤ -sell_threshold {-params.sell_threshold:+.2f}"
    else:
        action = AgentAction.HOLD
        why = f"score {score:+.3f} inside [-{params.sell_threshold:.2f}, {buy_cut:.2f}]"

    # Size scales with conviction so weak edges trade smaller; clamped to a floor.
    size_pct = round(_clamp(params.base_size_pct * confidence, 0.005, params.base_size_pct), 4)

    return {
        FieldName.ACTION: action,
        FieldName.CONFIDENCE: round(confidence, 4),
        FieldName.PRIMARY_EDGE: "policy:deterministic",
        FieldName.REASONING: f"Deterministic policy: {why}.",
        FieldName.RISK_FACTORS: risk_factors,
        FieldName.SIZE_PCT: size_pct,
        FieldName.STOP_ATR_X: params.stop_atr_x,
        FieldName.RR_RATIO: params.rr_ratio,
    }
