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
