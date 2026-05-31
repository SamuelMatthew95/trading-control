"""Tests for param_evolution — the pure source-editor behind the GitOps loop.

Editing a numeric constant in a live source file is the one genuinely risky step
of parameter automation, so it gets hostile-input coverage: a malformed or
out-of-bounds artifact must REFUSE, never corrupt the file.
"""

from __future__ import annotations

from api.services.param_evolution import (
    PARAM_BOUNDS,
    apply_param_change_to_source,
    validate_param_change,
)

_SRC = (
    "from typing import Final\n"
    "\n"
    "SIGNAL_CONFIDENCE_MIN_GATE: Final[float] = 0.50\n"
    "GRADE_EVERY_N_FILLS: Final[int] = 5  # grade cadence\n"
    "REDIS_PRICES_TTL_SECONDS: Final[int] = 150  # must exceed poll interval\n"
    "UNLISTED_PARAM: Final[float] = 1.0\n"
)


# ---------------------------------------------------------------------------
# validate_param_change
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# apply_param_change_to_source — happy path
# ---------------------------------------------------------------------------


def test_apply_edits_float_value():
    res = apply_param_change_to_source(_SRC, "SIGNAL_CONFIDENCE_MIN_GATE", 0.6)
    assert res.ok
    assert res.previous_value == 0.50
    assert res.new_value == 0.6
    assert "SIGNAL_CONFIDENCE_MIN_GATE: Final[float] = 0.6\n" in res.new_source
    # Only the target line changed.
    assert "GRADE_EVERY_N_FILLS: Final[int] = 5  # grade cadence\n" in res.new_source


def test_apply_preserves_inline_comment():
    res = apply_param_change_to_source(_SRC, "GRADE_EVERY_N_FILLS", 10)
    assert res.ok
    assert "GRADE_EVERY_N_FILLS: Final[int] = 10  # grade cadence\n" in res.new_source


def test_apply_int_field_rejects_fractional_value():
    # 7.5 is not a valid int — must refuse rather than truncate.
    res = apply_param_change_to_source(_SRC, "GRADE_EVERY_N_FILLS", 7.5)
    assert not res.ok
    assert res.error is not None


def test_apply_int_field_accepts_integral_float():
    res = apply_param_change_to_source(_SRC, "GRADE_EVERY_N_FILLS", 8.0)
    assert res.ok
    assert res.new_value == 8
    assert "GRADE_EVERY_N_FILLS: Final[int] = 8  # grade cadence\n" in res.new_source


def test_apply_only_changes_one_line():
    res = apply_param_change_to_source(_SRC, "SIGNAL_CONFIDENCE_MIN_GATE", 0.6)
    before = _SRC.splitlines()
    after = res.new_source.splitlines()
    diff = [(b, a) for b, a in zip(before, after, strict=True) if b != a]
    assert len(diff) == 1


# ---------------------------------------------------------------------------
# apply_param_change_to_source — refusals (file must stay safe)
# ---------------------------------------------------------------------------


def test_apply_refuses_unlisted_parameter():
    # UNLISTED_PARAM exists in the source but is not on the allowlist.
    res = apply_param_change_to_source(_SRC, "UNLISTED_PARAM", 2.0)
    assert not res.ok
    assert res.new_source is None


def test_apply_refuses_missing_line():
    res = apply_param_change_to_source("X: Final[int] = 1\n", "SIGNAL_CONFIDENCE_MIN_GATE", 0.6)
    assert not res.ok
    assert "no '" in (res.error or "")


def test_apply_refuses_out_of_bounds():
    res = apply_param_change_to_source(_SRC, "SIGNAL_CONFIDENCE_MIN_GATE", 0.99)
    assert not res.ok
    assert res.new_source is None


def test_apply_refuses_ambiguous_duplicate():
    dup = _SRC + "SIGNAL_CONFIDENCE_MIN_GATE: Final[float] = 0.55\n"
    res = apply_param_change_to_source(dup, "SIGNAL_CONFIDENCE_MIN_GATE", 0.6)
    assert not res.ok
    assert "refusing ambiguous" in (res.error or "")


def test_apply_noop_when_value_unchanged():
    res = apply_param_change_to_source(_SRC, "SIGNAL_CONFIDENCE_MIN_GATE", 0.50)
    assert not res.ok
    assert "no change needed" in (res.error or "")


def test_apply_does_not_touch_commented_or_other_lines():
    # A name that only appears in a comment must not be edited.
    src = "# SIGNAL_CONFIDENCE_MIN_GATE was 0.65\nOTHER: Final[int] = 1\n"
    res = apply_param_change_to_source(src, "SIGNAL_CONFIDENCE_MIN_GATE", 0.6)
    assert not res.ok


def test_apply_handles_underscored_int_literal():
    src = "AGENT_SUSPEND_TTL_SECONDS: Final[int] = 86_400\n"
    # Not on the allowlist, so it must refuse — but must not crash on 86_400.
    res = apply_param_change_to_source(src, "AGENT_SUSPEND_TTL_SECONDS", 1000)
    assert not res.ok  # not allowlisted


def test_real_constants_file_is_editable_end_to_end():
    """Smoke test against the REAL api/constants.py: a known tunable edits cleanly."""
    import pathlib

    src = pathlib.Path("api/constants.py").read_text()
    res = apply_param_change_to_source(src, "SIGNAL_CONFIDENCE_MIN_GATE", 0.55)
    assert res.ok, res.error
    assert res.new_source is not None
    assert res.new_source != src
    # The edited file must still be valid Python.
    import ast

    ast.parse(res.new_source)
