"""Plain-data parameter overrides — the SAFE core of the GitOps learning loop.

The learning loop tunes numeric parameters. Rather than have a bot rewrite lines
in ``api/constants.py`` (executing source code is risky — a bad edit could break
the app), the loop edits a plain-DATA file, ``config/param_overrides.json``, that
the code READS at startup. Data, not code:

  * A malformed or out-of-bounds override is REJECTED at load and the hand-authored
    code default is used — a bad artifact can never break a running process.
  * The reviewed PR diff is a one-line JSON change, trivial to read.
  * ``api/constants.py`` stays the authoritative default; overrides layer on top.

This module is pure (no IO beyond an explicit path read) and fully tested. The
GitOps script edits this JSON via :func:`apply_param_override`; ``constants.py``
applies it via :func:`load_overrides` at import time.

Bounds are the SAME ``PARAM_BOUNDS`` the editor enforces, so the load-time check
and the propose-time check can never drift.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

from api.services.param_evolution import PARAM_BOUNDS, validate_param_change

# Repo-relative default; override via env for tests / alternate deployments.
DEFAULT_OVERRIDES_PATH = "config/param_overrides.json"
_ENV_PATH = "PARAM_OVERRIDES_PATH"


def overrides_path() -> pathlib.Path:
    """Resolve the overrides file path (env-overridable)."""
    return pathlib.Path(os.environ.get(_ENV_PATH) or DEFAULT_OVERRIDES_PATH)


def _coerce_like_bounds(parameter: str, value: float) -> int | float:
    """Return int when both bounds are whole numbers (cadence-style params), else float."""
    lo, hi = PARAM_BOUNDS[parameter]
    if float(lo).is_integer() and float(hi).is_integer():
        return int(value)
    return float(value)


def sanitize_overrides(raw: dict[str, Any]) -> dict[str, int | float]:
    """Return only the entries that are safe to apply; silently drop the rest.

    An entry is kept iff the parameter is on the allowlist AND the value passes the
    same safe-bounds validation used when proposing the change. Anything else
    (unknown key, out-of-bounds, non-numeric) is dropped so a bad override file
    degrades to "use defaults", never to a crash or an unsafe value.
    """
    clean: dict[str, int | float] = {}
    if not isinstance(raw, dict):
        return clean
    for key, value in raw.items():
        if validate_param_change(str(key), value) is not None:
            continue
        clean[str(key)] = _coerce_like_bounds(str(key), float(value))
    return clean


def load_overrides(path: pathlib.Path | None = None) -> dict[str, int | float]:
    """Load + validate overrides from disk. Returns {} on any problem (missing file,
    bad JSON, unreadable) — the code defaults then stand, so startup never fails
    because of this file."""
    p = path or overrides_path()
    try:
        if not p.is_file():
            return {}
        raw = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return sanitize_overrides(raw)


def apply_param_override(
    raw_text: str, parameter: str, proposed_value: object
) -> tuple[bool, str | None, str | None]:
    """Return (ok, new_json_text, error) applying one override to the JSON document.

    Pure: takes and returns text, touches no files. Refuses (ok=False) on the same
    safety violations as the source editor — unknown/unsafe parameter or
    out-of-bounds value — so the GitOps script can never write a junk override.
    """
    err = validate_param_change(parameter, proposed_value)
    if err is not None:
        return False, None, err

    try:
        current = json.loads(raw_text) if raw_text.strip() else {}
        if not isinstance(current, dict):
            return False, None, "overrides file is not a JSON object"
    except json.JSONDecodeError as exc:
        return False, None, f"invalid JSON: {exc}"

    new_value = _coerce_like_bounds(parameter, float(proposed_value))  # type: ignore[arg-type]
    if current.get(parameter) == new_value:
        return False, None, "override already equals proposed value; no change needed"

    current[parameter] = new_value
    # Sorted keys + trailing newline => stable, reviewable diffs.
    new_text = json.dumps(current, indent=2, sort_keys=True) + "\n"
    return True, new_text, None
