"""CONFIG REPOSITORY — the single, Git-versioned source of truth for behaviour.

All tunable behaviour (signal weights, decision thresholds, hard risk limits)
lives in ``config/cognitive_config.json``. The running system only ever READS
it; it is never mutated at runtime. The ONLY way it changes is the GitOps path:

    proposal -> challenger -> backtest -> Pull Request -> human merge

This mirrors the safety model of ``api/services/param_overrides.py``: behaviour
is *data*, not code, every value is bounds-checked, and a malformed or
out-of-bounds file degrades to the hand-authored defaults rather than crashing
or applying something unsafe. A bad config artifact can never break the process
and can never push a value outside its guardrail.

Pure module: no Redis, no DB, no git. Fully unit-tested.
"""

from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass
from typing import Any

# The signals the deterministic decision engine scores. Risk is NOT scored — it
# is a separate hard gate (see cognitive/risk.py), matching the system spec.
WEIGHT_KEYS: tuple[str, ...] = ("news", "tech", "macro")

# Per-field safe bounds (inclusive). A value outside its range is refused by
# validation and dropped at load. The learning loop may TUNE within these
# guardrails via a reviewed PR, but automation can never set a wild value.
WEIGHT_BOUNDS: tuple[float, float] = (0.0, 1.0)
BUY_THRESHOLD_BOUNDS: tuple[float, float] = (0.0, 0.95)
SELL_THRESHOLD_BOUNDS: tuple[float, float] = (-0.95, 0.0)
MAX_POSITION_SIZE_BOUNDS: tuple[float, float] = (0.001, 0.5)
MAX_DAILY_LOSS_BOUNDS: tuple[float, float] = (0.001, 0.25)
MAX_EXPOSURE_BOUNDS: tuple[float, float] = (0.01, 1.0)

DEFAULT_OVERRIDES_PATH = "config/cognitive_config.json"
_ENV_PATH = "COGNITIVE_CONFIG_PATH"

# Hand-authored defaults — the authoritative fallback if the file is missing or
# invalid. Weights are advisory inputs to a deterministic formula; they need not
# sum to 1 (the thresholds define the trade band).
DEFAULTS: dict[str, Any] = {
    "version": 1,
    "weights": {"news": 0.34, "tech": 0.33, "macro": 0.33},
    "buy_threshold": 0.15,
    "sell_threshold": -0.15,
    "risk": {
        "max_position_size_pct": 0.05,
        "max_daily_loss_pct": 0.02,
        "max_exposure_pct": 0.30,
    },
}


@dataclass(frozen=True)
class CognitiveConfig:
    """Immutable behaviour snapshot scored by the deterministic decision engine."""

    version: int
    weights: dict[str, float]
    buy_threshold: float
    sell_threshold: float
    max_position_size_pct: float
    max_daily_loss_pct: float
    max_exposure_pct: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CognitiveConfig:
        """Build from the nested JSON shape, falling back to defaults per field."""
        weights_in = data.get("weights") or {}
        weights = {k: float(weights_in.get(k, DEFAULTS["weights"][k])) for k in WEIGHT_KEYS}
        risk = data.get("risk") or {}
        return cls(
            version=int(data.get("version", DEFAULTS["version"])),
            weights=weights,
            buy_threshold=float(data.get("buy_threshold", DEFAULTS["buy_threshold"])),
            sell_threshold=float(data.get("sell_threshold", DEFAULTS["sell_threshold"])),
            max_position_size_pct=float(
                risk.get("max_position_size_pct", DEFAULTS["risk"]["max_position_size_pct"])
            ),
            max_daily_loss_pct=float(
                risk.get("max_daily_loss_pct", DEFAULTS["risk"]["max_daily_loss_pct"])
            ),
            max_exposure_pct=float(
                risk.get("max_exposure_pct", DEFAULTS["risk"]["max_exposure_pct"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Nested JSON shape, identical in structure to the on-disk file."""
        return {
            "version": self.version,
            "weights": dict(self.weights),
            "buy_threshold": self.buy_threshold,
            "sell_threshold": self.sell_threshold,
            "risk": {
                "max_position_size_pct": self.max_position_size_pct,
                "max_daily_loss_pct": self.max_daily_loss_pct,
                "max_exposure_pct": self.max_exposure_pct,
            },
        }


DEFAULT_CONFIG = CognitiveConfig.from_dict(DEFAULTS)


def _in_bounds(value: Any, bounds: tuple[float, float]) -> bool:
    """True iff ``value`` is a real number inside ``bounds`` (bool rejected)."""
    if value is None or isinstance(value, bool):
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    lo, hi = bounds
    return lo <= numeric <= hi


def validate_config_dict(data: dict[str, Any]) -> list[str]:
    """Return a list of human-readable errors; empty means the config is safe.

    Used by the gitops path and the challenger so a proposed config can never be
    PR'd if it would set an unsafe or malformed value.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["config is not a JSON object"]

    weights = data.get("weights")
    if not isinstance(weights, dict):
        errors.append("weights must be an object with news/tech/macro")
    else:
        for key in WEIGHT_KEYS:
            if key not in weights:
                errors.append(f"weights.{key} is missing")
            elif not _in_bounds(weights[key], WEIGHT_BOUNDS):
                errors.append(f"weights.{key}={weights[key]!r} outside {WEIGHT_BOUNDS}")

    if not _in_bounds(data.get("buy_threshold"), BUY_THRESHOLD_BOUNDS):
        errors.append(f"buy_threshold outside {BUY_THRESHOLD_BOUNDS}")
    if not _in_bounds(data.get("sell_threshold"), SELL_THRESHOLD_BOUNDS):
        errors.append(f"sell_threshold outside {SELL_THRESHOLD_BOUNDS}")

    buy = data.get("buy_threshold")
    sell = data.get("sell_threshold")
    if _in_bounds(buy, BUY_THRESHOLD_BOUNDS) and _in_bounds(sell, SELL_THRESHOLD_BOUNDS):
        if float(sell) >= float(buy):
            errors.append("sell_threshold must be strictly below buy_threshold")

    risk = data.get("risk")
    if not isinstance(risk, dict):
        errors.append("risk must be an object")
    else:
        for key, bounds in (
            ("max_position_size_pct", MAX_POSITION_SIZE_BOUNDS),
            ("max_daily_loss_pct", MAX_DAILY_LOSS_BOUNDS),
            ("max_exposure_pct", MAX_EXPOSURE_BOUNDS),
        ):
            if not _in_bounds(risk.get(key), bounds):
                errors.append(f"risk.{key}={risk.get(key)!r} outside {bounds}")
    return errors


def overrides_path(path: pathlib.Path | None = None) -> pathlib.Path:
    """Resolve the config file path (env-overridable for tests / deployments)."""
    if path is not None:
        return path
    return pathlib.Path(os.environ.get(_ENV_PATH) or DEFAULT_OVERRIDES_PATH)


def load_config(path: pathlib.Path | None = None) -> CognitiveConfig:
    """Load + validate config from disk; returns DEFAULT_CONFIG on any problem.

    Never raises: a missing file, bad JSON, or an out-of-bounds value all
    degrade to the safe hand-authored defaults so startup can never fail because
    of this file.
    """
    resolved = overrides_path(path)
    try:
        if not resolved.is_file():
            return DEFAULT_CONFIG
        raw = json.loads(resolved.read_text())
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CONFIG
    if validate_config_dict(raw):
        return DEFAULT_CONFIG
    return CognitiveConfig.from_dict(raw)


def clamp_weight(value: float) -> float:
    """Clamp a weight into its safe bounds."""
    lo, hi = WEIGHT_BOUNDS
    return max(lo, min(hi, value))
