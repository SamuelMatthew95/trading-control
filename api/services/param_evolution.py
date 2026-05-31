"""Parameter-evolution source editing — the pure core of the GitOps loop.

ProposalApplier turns a PARAMETER_CHANGE proposal into a ``pr_request`` artifact
on ``STREAM_GITHUB_PRS``. A scheduled GitHub Action reads those artifacts (via
``GET /learning/pending-param-changes``) and, for each, calls
``apply_param_change_to_source`` to edit the value in ``api/constants.py``, then
opens a PR for human review. No value is mutated at runtime — the source file is
the single source of truth and every change is a reviewable diff.

This module is PURE text-editing: no IO, no Redis, no git, no GitHub. That keeps
the only risky part — rewriting a numeric constant in a live source file — fully
deterministic and unit-testable. The Action and CLI wrap it with the IO.

Safety invariants enforced here (a malformed/hostile artifact must NOT corrupt
the file):
  * Only a known ``NAME: Final[int|float] = <number>`` line may be edited.
  * The parameter name must be a plain UPPER_SNAKE identifier.
  * The proposed value must parse as the SAME numeric type already declared.
  * The proposed value must lie within the per-parameter safe bound (if any).
  * Exactly one matching line must exist; zero or many => refuse.
  * Any inline ``# comment`` on the line is preserved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Per-parameter safe bounds (inclusive). A proposed value outside its range is
# refused — the learning loop may TUNE within guardrails but never set a wild or
# unsafe value via automation. Parameters absent here are not auto-editable.
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "SIGNAL_CONFIDENCE_MIN_GATE": (0.30, 0.80),
    "EXECUTION_DECISION_THRESHOLD": (0.40, 0.80),
    "EXECUTION_DECISION_THRESHOLD_MEMORY": (0.30, 0.80),
    "STOP_LOSS_PCT": (0.01, 0.15),
    "TAKE_PROFIT_PCT": (0.02, 0.40),
    "MAX_RISK_PER_TRADE_PCT": (0.005, 0.05),
    "KELLY_FRACTION_SCALE": (0.05, 0.50),
    "GRADE_EVERY_N_FILLS": (1, 100),
    "IC_UPDATE_EVERY_N_FILLS": (1, 100),
    "REFLECT_EVERY_N_FILLS": (1, 100),
    "SIGNAL_EVERY_N_TICKS": (1, 100),
}

# NAME: Final[int|float] = <number>   [ # comment ]
_LINE_RE = re.compile(
    r"^(?P<prefix>(?P<name>[A-Z][A-Z0-9_]*)\s*:\s*Final\[(?P<typ>int|float)\]\s*=\s*)"
    r"(?P<value>-?\d+(?:_\d+)*(?:\.\d+)?)"
    r"(?P<suffix>\s*(?:#.*)?)$"
)

_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True)
class ParamEditResult:
    """Outcome of a parameter edit attempt."""

    ok: bool
    parameter: str
    previous_value: float | int | None = None
    new_value: float | int | None = None
    new_source: str | None = None  # full edited file text when ok
    error: str | None = None


def _coerce(typ: str, raw: object) -> int | float | None:
    """Parse ``raw`` as the declared type (int or float); None if it cannot."""
    try:
        if typ == "int":
            # Reject 0.5 for an int field: float that isn't integral is invalid.
            f = float(raw)  # type: ignore[arg-type]
            if f != int(f):
                return None
            return int(f)
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def validate_param_change(parameter: str, proposed_value: object) -> str | None:
    """Return an error string if this change is not safe to apply, else None.

    Pure precheck usable by the API/CLI before touching the file, so a bad
    artifact is rejected early with a clear reason.
    """
    if not parameter or not _NAME_RE.match(parameter):
        return f"invalid parameter name: {parameter!r}"
    if parameter not in PARAM_BOUNDS:
        return f"parameter not in the auto-editable allowlist: {parameter}"
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


def apply_param_change_to_source(
    source: str, parameter: str, proposed_value: object
) -> ParamEditResult:
    """Return a ParamEditResult with the edited ``source`` text (does not write files).

    Refuses (ok=False) on any safety violation: unknown/unsafe parameter, type
    mismatch, out-of-bounds value, or a non-unique match. The inline comment and
    declared type are preserved; only the numeric literal changes.
    """
    err = validate_param_change(parameter, proposed_value)
    if err is not None:
        return ParamEditResult(ok=False, parameter=parameter, error=err)

    lines = source.splitlines(keepends=True)
    matches: list[tuple[int, re.Match[str]]] = []
    for idx, line in enumerate(lines):
        stripped = line.rstrip("\n")
        m = _LINE_RE.match(stripped)
        if m and m.group("name") == parameter:
            matches.append((idx, m))

    if not matches:
        return ParamEditResult(
            ok=False, parameter=parameter, error=f"no '{parameter}: Final[...] = ...' line found"
        )
    if len(matches) > 1:
        return ParamEditResult(
            ok=False,
            parameter=parameter,
            error=f"{len(matches)} declarations of {parameter} found; refusing ambiguous edit",
        )

    idx, m = matches[0]
    typ = m.group("typ")
    new_typed = _coerce(typ, proposed_value)
    if new_typed is None:
        return ParamEditResult(
            ok=False,
            parameter=parameter,
            error=f"proposed value {proposed_value!r} is not a valid {typ}",
        )
    previous_typed = _coerce(typ, m.group("value").replace("_", ""))

    # Compare by VALUE, not by string: 0.50 -> 0.5 is the same number, not a change.
    if previous_typed == new_typed:
        return ParamEditResult(
            ok=False,
            parameter=parameter,
            previous_value=previous_typed,
            new_value=new_typed,
            error="proposed value equals current value; no change needed",
        )

    newline = "\n" if lines[idx].endswith("\n") else ""
    rebuilt = f"{m.group('prefix')}{new_typed}{m.group('suffix')}{newline}"

    new_lines = list(lines)
    new_lines[idx] = rebuilt
    return ParamEditResult(
        ok=True,
        parameter=parameter,
        previous_value=previous_typed,
        new_value=new_typed,
        new_source="".join(new_lines),
    )
