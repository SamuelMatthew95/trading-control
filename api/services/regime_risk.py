"""Regime-aware risk posture — one source of truth for how a bearish (risk-off)
macro regime tightens risk across the whole system.

A risk-off macro regime (the benchmark's recent daily trend is down — see
:func:`api.services.market_intel.fetch_macro_regime`) is the dominant loss
regime for a long book: momentum entries chase a falling market, winners
round-trip on dead-cat bounces, and a losing day compounds. The learning loop
flags this recurringly as a ``regime_adjustment`` proposal ("risk management
insufficient, significant losses" in a bearish regime).

Rather than scatter ``if regime == RISK_OFF`` branches across the
ReasoningAgent's sizing, RiskGuardian's exits, and the daily-loss check, every
regime-conditional risk parameter is resolved here. Consumers read the macro
regime where they already have it (the reasoning context, or the RiskGuardian
cache read) and ask this module for the effective parameter.

**Fail-safe invariant:** every risk parameter here only ever TIGHTENS in an
explicit risk-off regime and is a no-op for every other input. An unknown /
risk-on / neutral / missing / stale regime always yields the DEFAULT parameter,
so a lost regime read can never loosen a RISK parameter — only the explicit
RISK_OFF signal narrows it.

The one deliberate exception is :func:`buy_threshold`: the risk-ON complement to
the long-entry tightening. It EASES (lowers) the long-entry score cut in an
explicit risk-on regime — but only on the entry side, and only when the signal's
own momentum is not bearish: it never touches the SELL cut, a stop, or any exit,
so it cannot weaken capital preservation. It is the mirror of the risk-off
long-gate raises, not a loosening of any risk limit.
"""

from __future__ import annotations

from typing import Any

from api.constants import (
    DAILY_LOSS_LIMIT_PCT,
    RISK_OFF_DAILY_LOSS_LIMIT_PCT,
    RISK_OFF_EXECUTION_DECISION_THRESHOLD,
    RISK_OFF_MIN_CONFIDENCE,
    RISK_OFF_SIZE_MULTIPLIER,
    RISK_OFF_STOP_LOSS_PCT,
    RISK_OFF_TAKE_PROFIT_PCT,
    RISK_ON_BUY_THRESHOLD_DELTA,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    FieldName,
    MacroRegime,
)


def regime_of(macro: Any) -> str | None:
    """Extract the regime string from a macro-regime payload, or ``None``.

    Accepts the dict shape that ``fetch_macro_regime`` /
    ``read_cached_macro_regime`` return (``{"regime": "risk_off", ...}``) and
    fails safe on anything else — ``None`` / ``{}`` (no regime read yet) and any
    malformed non-dict value all yield ``None``, so a bad payload degrades to
    the default (un-tightened) posture instead of crashing the decision path.
    """
    if not isinstance(macro, dict):
        return None
    return macro.get(FieldName.REGIME)


def is_risk_off(regime: str | None) -> bool:
    """True only when the macro regime is explicitly risk-off (bearish)."""
    return regime == MacroRegime.RISK_OFF


def is_risk_on(regime: str | None) -> bool:
    """True only when the macro regime is explicitly risk-on (bullish)."""
    return regime == MacroRegime.RISK_ON


def buy_threshold(regime: str | None, default: float, momentum: float = 0.0) -> float:
    """Score cut a NEW long entry must clear — EASED in a confirmed risk-on regime.

    The mirror of the risk-off long-gate raises (``min_confidence`` /
    ``execution_threshold``): where a bearish regime RAISES the bar a new long must
    clear, an explicit bullish regime LOWERS the deterministic policy's BUY cut by
    ``RISK_ON_BUY_THRESHOLD_DELTA``. The cut is eased ONLY when BOTH hold:

    - the regime is explicitly risk-on (every other input — risk-off / neutral /
      unknown / missing regime — returns ``default`` unchanged), AND
    - the signal's own ``momentum`` is not bearish (``>= 0``). The regime tailwind
      must never drag a falling-momentum signal into a long; with the seed weights
      a bearish-momentum long already cannot clear even the eased cut, and this
      guard makes that an explicit invariant rather than an artifact of the current
      weights.

    Strictly entry-side and fail-safe by construction:
    - It only ever moves the BUY cut. The caller leaves the SELL cut and the
      reported score untouched, so easing this can never suppress a de-risking
      sell or any RiskGuardian exit — the capital-preservation path is intact.
    - A lost or malformed regime read (``None``) returns ``default``, so a missing
      regime can never ease the bar.
    - Floored at 0.0 so an oversized delta can never make the cut negative (which
      would buy on any positive score).
    """
    if is_risk_on(regime) and momentum >= 0:
        return max(0.0, default - RISK_ON_BUY_THRESHOLD_DELTA)
    return default


def stop_loss_pct(regime: str | None, *, is_long: bool) -> float:
    """Hard stop-loss fraction — tightened for LONGs in a risk-off regime."""
    if is_long and is_risk_off(regime):
        return RISK_OFF_STOP_LOSS_PCT
    return STOP_LOSS_PCT


def take_profit_pct(regime: str | None, *, is_long: bool) -> float:
    """Take-profit fraction — tightened for LONGs in a risk-off regime so
    fragile gains are banked before a bearish leg gives them back."""
    if is_long and is_risk_off(regime):
        return RISK_OFF_TAKE_PROFIT_PCT
    return TAKE_PROFIT_PCT


def daily_loss_limit_pct(regime: str | None) -> float:
    """Portfolio daily-loss limit — tightened in a risk-off regime so the kill
    switch trips sooner on a compounding losing day."""
    if is_risk_off(regime):
        return RISK_OFF_DAILY_LOSS_LIMIT_PCT
    return DAILY_LOSS_LIMIT_PCT


def size_multiplier(regime: str | None, *, is_long: bool) -> float:
    """Scale for a NEW entry's position size. A long entry is shrunk in a
    risk-off regime (don't size up into a falling market); shorts and every
    other regime are unscaled (1.0)."""
    if is_long and is_risk_off(regime):
        return RISK_OFF_SIZE_MULTIPLIER
    return 1.0


def min_confidence(regime: str | None, default: float, *, is_long: bool) -> float:
    """Minimum conviction required to OPEN a new long entry.

    Shrinking a long in a bearish regime still TAKES every marginal long; this
    is the complementary entry gate that REJECTS them. In a risk-off regime a
    new long must clear ``RISK_OFF_MIN_CONFIDENCE`` to open at all, so the book
    stops chasing weak momentum into a falling market. Resolved as
    ``max(default, RISK_OFF_MIN_CONFIDENCE)`` so the posture can only ever RAISE
    the bar — never lower an already-stricter operator/control-plane floor.
    Shorts and every non-risk-off/unknown/missing regime keep ``default``.
    """
    if is_long and is_risk_off(regime):
        return max(default, RISK_OFF_MIN_CONFIDENCE)
    return default


def execution_threshold(regime: str | None, default: float, *, is_long: bool) -> float:
    """Weighted-score bar a NEW long entry must clear at the ExecutionEngine gate.

    ``min_confidence`` gates on the raw *signal* confidence at the reasoning
    node; this is the downstream complement at the *execution* gate, where the
    blended score (signal·0.5 + reasoning·0.3 + historical·0.2) is checked. In a
    risk-off regime a new long must clear ``RISK_OFF_EXECUTION_DECISION_THRESHOLD``
    to execute, so marginal momentum longs — the dominant over-trading /
    low-win-rate loss source in a bearish tape — are filtered while
    high-conviction longs still trade. Resolved as
    ``max(default, RISK_OFF_EXECUTION_DECISION_THRESHOLD)`` so the posture can
    only ever RAISE the bar, never lower an operator/control-plane override (e.g.
    the memory-mode threshold). SELL exits keep ``default`` so the book can
    always de-risk; shorts and every non-risk-off/unknown/missing regime keep
    ``default``.
    """
    if is_long and is_risk_off(regime):
        return max(default, RISK_OFF_EXECUTION_DECISION_THRESHOLD)
    return default
