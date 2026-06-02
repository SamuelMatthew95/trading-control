"""Apply committed config overrides at startup — the read side of auto-PR GitOps.

The learning loop's `PARAMETER_CHANGE` proposals open a config-only PR that
writes a JSON file under ``config/parameter_overrides/``. A human reviews and
merges it; on the NEXT deploy this loader reads those files and applies the
values over ``settings`` — so a merged config change actually takes effect
(version-controlled, reviewed, never live-mutated and never source code).

Defensive by construction: a missing directory, malformed JSON, an unknown
setting, or a value that won't coerce to the field's current type is skipped
with a warning — a bad override can never crash startup.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from api.constants import PARAMETER_OVERRIDES_DIR, FieldName
from api.observability import log_structured


def _coerce(current: Any, proposed: Any) -> Any:
    """Cast ``proposed`` to the type of ``current`` (bools handled explicitly)."""
    if isinstance(current, bool):
        if isinstance(proposed, bool):
            return proposed
        return str(proposed).strip().lower() in {"1", "true", "yes", "on"}
    if current is None:
        return proposed
    return type(current)(proposed)


def apply_parameter_overrides(settings_obj: Any, *, root: str | Path = ".") -> list[str]:
    """Apply every override file to ``settings_obj``. Returns applied param names."""
    overrides_dir = Path(root) / PARAMETER_OVERRIDES_DIR
    if not overrides_dir.is_dir():
        return []

    applied: list[str] = []
    for path in sorted(overrides_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            log_structured("warning", "config_override_unreadable", file=str(path), exc_info=True)
            continue

        parameter = str(record.get(FieldName.PARAMETER) or "").strip()
        if not parameter or not hasattr(settings_obj, parameter):
            log_structured("warning", "config_override_unknown_param", parameter=parameter)
            continue
        try:
            value = _coerce(getattr(settings_obj, parameter), record.get(FieldName.PROPOSED_VALUE))
            setattr(settings_obj, parameter, value)
        except (TypeError, ValueError):
            log_structured(
                "warning", "config_override_bad_value", parameter=parameter, exc_info=True
            )
            continue
        applied.append(parameter)
        log_structured("info", "config_override_applied", parameter=parameter, value=value)
    return applied
