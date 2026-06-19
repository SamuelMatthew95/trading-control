"""Parameter-evolution safety bounds + validation — shared core of the GitOps loop.

The learning loop tunes a small allowlist of numeric parameters. It does NOT edit
source code: it writes a plain-DATA file (``config/param_overrides.json``) that the
constants loader reads and validates at startup (see ``api/services/param_overrides``).

This module owns the single source of truth for WHICH parameters are auto-tunable
and their SAFE BOUNDS, plus the pure validation used in three places that must
never drift:
  * ProposalApplier — before emitting a pr_request artifact,
  * the /learning/pending-param-changes endpoint — before surfacing one,
  * the constants loader — before applying an override at startup.

Pure: no IO, no Redis, no git. Fully unit-tested.
"""

from __future__ import annotations

import re

# Per-parameter safe bounds (inclusive). A proposed value outside its range is
# refused — the learning loop may TUNE within guardrails but never set a wild or
# unsafe value via automation. Parameters absent here are not auto-editable.
#
# IMPORTANT: only ``api/constants.py``-resident constants belong here. The override
# mechanism layers values onto module-level constants at import; it does NOT touch
# pydantic Settings (config.py / env). Listing a Settings-only param (e.g.
# GRADE_EVERY_N_FILLS) would let the loop "propose" a change that silently never
# applies — a dead end. Keep this set == the tunables constants.py publishes.
# (test_param_overrides asserts every key resolves on api.constants.)
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "SIGNAL_CONFIDENCE_MIN_GATE": (0.30, 0.80),
    "EXECUTION_DECISION_THRESHOLD": (0.40, 0.80),
    "EXECUTION_DECISION_THRESHOLD_MEMORY": (0.30, 0.80),
    "STOP_LOSS_PCT": (0.01, 0.15),
    "TAKE_PROFIT_PCT": (0.02, 0.40),
    "MAX_RISK_PER_TRADE_PCT": (0.005, 0.05),
    "KELLY_FRACTION_SCALE": (0.05, 0.50),
    # Trailing-stop ratchet (RiskGuardian). ARM low bound stays above typical
    # slippage noise; GIVEBACK 1.0 would never trail, 0.0 would exit on the
    # first downtick — both excluded by the bounds.
    "TRAILING_STOP_ARM_PCT": (0.005, 0.08),
    "TRAILING_STOP_GIVEBACK_FRAC": (0.10, 0.80),
    # Stale-position reaper (RiskGuardian). Whole-number bounds → int coercion.
    "STALE_POSITION_MAX_AGE_SECONDS": (1800, 259200),
    "STALE_POSITION_PNL_BAND_PCT": (0.0, 0.05),
    # GradeAgent's rate-limit response. Upper bound mirrors LLM_DELAY_MAX_MS in
    # api/constants.py (literal here — this module must stay import-cycle-free).
    # Whole-number bounds → the override is coerced to int, matching the constant.
    "LLM_CALL_DELAY_MS": (0, 2000),
}

_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Maps a reflection hypothesis's semantic category (its ``type``) onto the
# auto-tunable parameter that category governs. A hypothesis that names one of
# these concerns — e.g. "signal confidence is too low" — IS a parameter-tuning
# request, NOT a request for new code. Routing it to the auto-applyable
# PARAMETER_CHANGE path (instead of the REGIME_ADJUSTMENT human-design issue)
# is what stops the learning loop re-filing the same generic proposal as a fresh
# GitHub issue every day (the recurring-issue bug: #324 → #334 → …). Proposal
# dedup is date-keyed and resets daily, so a mis-routed parameter hypothesis
# reopens an issue every cycle with no path to ever auto-resolve.
#
# Only concrete, single-parameter concepts belong here. Genuinely broad strategy
# concerns ("regime", vague "risk_management") stay OUT so they still route to
# the human-design REGIME_ADJUSTMENT issue. Every value MUST be a key in
# PARAM_BOUNDS (asserted by test_param_evolution).
HYPOTHESIS_PARAM_MAP: dict[str, str] = {
    "signal_confidence": "SIGNAL_CONFIDENCE_MIN_GATE",
    "confidence": "SIGNAL_CONFIDENCE_MIN_GATE",
    "confidence_gate": "SIGNAL_CONFIDENCE_MIN_GATE",
    # Defensive aliases for the same confidence concern — the reflection LLM is
    # not normalized upstream, so a near-miss category label ("low_confidence",
    # "signal_confidence_too_low") must still auto-route to PARAMETER_CHANGE
    # rather than slip through to a recurring REGIME_ADJUSTMENT GitHub issue
    # (the #324 → #334 recurrence: issue #334's hypothesis was literally
    # "signal confidence is too low").
    "low_confidence": "SIGNAL_CONFIDENCE_MIN_GATE",
    "signal_confidence_too_low": "SIGNAL_CONFIDENCE_MIN_GATE",
    "execution_threshold": "EXECUTION_DECISION_THRESHOLD",
    "execution_decision_threshold": "EXECUTION_DECISION_THRESHOLD",
    "decision_threshold": "EXECUTION_DECISION_THRESHOLD",
    "execution_threshold_too_low": "EXECUTION_DECISION_THRESHOLD",
    "decision_threshold_too_low": "EXECUTION_DECISION_THRESHOLD",
    "stop_loss": "STOP_LOSS_PCT",
    "take_profit": "TAKE_PROFIT_PCT",
    "risk_per_trade": "MAX_RISK_PER_TRADE_PCT",
    "position_size": "MAX_RISK_PER_TRADE_PCT",
    "position_sizing": "MAX_RISK_PER_TRADE_PCT",
    "kelly": "KELLY_FRACTION_SCALE",
    "trailing_stop": "TRAILING_STOP_ARM_PCT",
}


def parameter_for_hypothesis(hypothesis_type: str | None) -> str | None:
    """Return the auto-tunable parameter a hypothesis category governs, or None.

    Pure. ``None`` for an unknown / empty / genuinely-strategic category, which
    keeps those on the human-design REGIME_ADJUSTMENT path. Used by the
    StrategyProposer to classify a parameter-shaped hypothesis as a
    PARAMETER_CHANGE rather than a recurring REGIME_ADJUSTMENT GitHub issue.
    """
    if not hypothesis_type:
        return None
    return HYPOTHESIS_PARAM_MAP.get(hypothesis_type.strip().lower())


def validate_param_change(parameter: str, proposed_value: object) -> str | None:
    """Return an error string if this change is not safe to apply, else None.

    Enforced everywhere a parameter change is proposed, surfaced, or applied, so
    an unknown key, non-numeric value, or out-of-bounds value is rejected
    consistently and a bad artifact can never reach the running app.
    """
    if not parameter or not _NAME_RE.match(parameter):
        return f"invalid parameter name: {parameter!r}"
    if parameter not in PARAM_BOUNDS:
        return f"parameter not in the auto-editable allowlist: {parameter}"
    # bool is an int subclass — reject it explicitly (True/False are not values).
    if proposed_value is None or isinstance(proposed_value, bool):
        return f"proposed value must be numeric, got {proposed_value!r}"
    try:
        numeric = float(proposed_value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return f"proposed value is not numeric: {proposed_value!r}"
    lo, hi = PARAM_BOUNDS[parameter]
    if not (lo <= numeric <= hi):
        return f"proposed value {numeric} outside safe bounds [{lo}, {hi}] for {parameter}"
    return None


def tunable_parameters() -> dict[str, dict[str, float]]:
    """The auto-editable parameters with their CURRENT value + safe bounds.

    Fed to the ReflectionAgent prompt so the LLM proposes concrete, in-bounds
    parameter changes (not prose), and read by the StrategyProposer to stamp the
    current value onto a PARAMETER_CHANGE so the applier can open a real config
    PR. A parameter whose current value can't be resolved as a finite number is
    omitted — it can't be proposed against safely.
    """
    from api import constants  # noqa: PLC0415  (avoid an import cycle at module load)

    out: dict[str, dict[str, float]] = {}
    for name, (lo, hi) in PARAM_BOUNDS.items():
        current = getattr(constants, name, None)
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            continue
        out[name] = {"current": float(current), "min": float(lo), "max": float(hi)}
    return out
