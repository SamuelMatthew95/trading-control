"""Tests for param_evolution — the safe-bounds allowlist + validation.

This is the single source of truth for which parameters are auto-tunable and
their safe ranges, enforced identically at propose-, surface-, and apply-time.
"""

from __future__ import annotations

from api import constants as _constants
from api.services.param_evolution import PARAM_BOUNDS, validate_param_change


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
