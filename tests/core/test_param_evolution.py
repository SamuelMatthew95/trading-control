"""Tests for param_evolution — the safe-bounds allowlist + validation.

This is the single source of truth for which parameters are auto-tunable and
their safe ranges, enforced identically at propose-, surface-, and apply-time.
"""

from __future__ import annotations

from api import constants as _constants
from api.services.param_evolution import (
    HYPOTHESIS_PARAM_MAP,
    PARAM_BOUNDS,
    parameter_for_hypothesis,
    validate_param_change,
)


def test_validate_rejects_unknown_parameter():
    assert validate_param_change("NOT_A_REAL_PARAM", 1.0) is not None


def test_validate_rejects_non_identifier():
    assert validate_param_change("rm -rf /", 1.0) is not None
    assert validate_param_change("lower_case", 1.0) is not None


def test_validate_rejects_non_numeric():
    assert validate_param_change("SIGNAL_CONFIDENCE_MIN_GATE", "abc") is not None
    assert validate_param_change("SIGNAL_CONFIDENCE_MIN_GATE", None) is not None


def test_validate_rejects_bool():
    # bool is an int subclass — must be explicitly rejected.
    assert validate_param_change("SIGNAL_CONFIDENCE_MIN_GATE", True) is not None


def test_validate_rejects_out_of_bounds():
    lo, hi = PARAM_BOUNDS["SIGNAL_CONFIDENCE_MIN_GATE"]
    assert validate_param_change("SIGNAL_CONFIDENCE_MIN_GATE", hi + 0.1) is not None
    assert validate_param_change("SIGNAL_CONFIDENCE_MIN_GATE", lo - 0.1) is not None


def test_validate_accepts_in_bounds():
    assert validate_param_change("SIGNAL_CONFIDENCE_MIN_GATE", 0.6) is None


def test_validate_accepts_inclusive_bounds():
    lo, hi = PARAM_BOUNDS["STOP_LOSS_PCT"]
    assert validate_param_change("STOP_LOSS_PCT", lo) is None
    assert validate_param_change("STOP_LOSS_PCT", hi) is None


def test_every_allowlisted_param_resolves_on_constants():
    """CRITICAL: every tunable must actually exist on api.constants, or the override
    would silently never apply (a dead-end proposal). Guards PARAM_BOUNDS from
    listing a Settings-only or misspelled name."""
    for name in PARAM_BOUNDS:
        assert hasattr(_constants, name), f"{name} in PARAM_BOUNDS but not defined on api.constants"
        assert isinstance(getattr(_constants, name), (int, float))


def test_default_values_are_within_their_own_bounds():
    """The hand-authored default must itself satisfy its bound — else the first
    override would be the only legal value, which signals a wrong bound."""
    for name, (lo, hi) in PARAM_BOUNDS.items():
        val = float(getattr(_constants, name))
        assert lo <= val <= hi, f"default {name}={val} outside its bound [{lo}, {hi}]"


# ---------------------------------------------------------------------------
# Hypothesis → parameter mapping (issue #334 — stop the recurring proposal)
# ---------------------------------------------------------------------------


def test_every_mapped_parameter_is_auto_tunable():
    """Every parameter a hypothesis can map to MUST be in PARAM_BOUNDS, or the
    StrategyProposer would route a hypothesis to a parameter the loop can't
    actually tune — re-creating the dead-end the mapping exists to fix."""
    for hyp_type, param in HYPOTHESIS_PARAM_MAP.items():
        assert param in PARAM_BOUNDS, f"{hyp_type!r} maps to {param}, not in PARAM_BOUNDS"


def test_signal_confidence_hypothesis_maps_to_gate():
    """The exact category from issue #334 resolves to the confidence gate."""
    assert parameter_for_hypothesis("signal_confidence") == "SIGNAL_CONFIDENCE_MIN_GATE"
    # Case / whitespace insensitive — LLM output is not normalized upstream.
    assert parameter_for_hypothesis("  Signal_Confidence  ") == "SIGNAL_CONFIDENCE_MIN_GATE"


def test_genuinely_strategic_categories_stay_unmapped():
    """Broad strategy concerns must return None so they still route to the
    human-design REGIME_ADJUSTMENT issue, not the parameter queue."""
    for category in ("regime", "risk_management", "new_strategy", "", None):
        assert parameter_for_hypothesis(category) is None


def test_near_miss_confidence_aliases_route_to_gate():
    """Defensive aliases for the #334 confidence concern resolve to the gate so a
    slightly-different LLM category label can't reopen the recurring issue."""
    for alias in ("low_confidence", "signal_confidence_too_low"):
        assert parameter_for_hypothesis(alias) == "SIGNAL_CONFIDENCE_MIN_GATE"
    for alias in ("execution_threshold_too_low", "decision_threshold_too_low"):
        assert parameter_for_hypothesis(alias) == "EXECUTION_DECISION_THRESHOLD"
