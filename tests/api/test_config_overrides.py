"""Tests for the startup config-override loader (auto-PR read side)."""

from __future__ import annotations

import json
from pathlib import Path

from api.constants import PARAMETER_OVERRIDES_DIR, FieldName
from api.services.config_overrides import apply_parameter_overrides


class _Settings:
    REASONING_COOLDOWN_SECONDS: float = 60.0
    PROMPT_EVOLUTION_ENABLED: bool = True


def _write_override(root: Path, parameter: str, value: object) -> None:
    d = root / PARAMETER_OVERRIDES_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{parameter}.json").write_text(
        json.dumps({FieldName.PARAMETER: parameter, FieldName.PROPOSED_VALUE: value})
    )


def test_no_dir_returns_empty(tmp_path):
    assert apply_parameter_overrides(_Settings(), root=tmp_path) == []


def test_applies_known_override_with_type_coercion(tmp_path):
    s = _Settings()
    _write_override(tmp_path, "REASONING_COOLDOWN_SECONDS", "90")  # string → float
    applied = apply_parameter_overrides(s, root=tmp_path)
    assert applied == ["REASONING_COOLDOWN_SECONDS"]
    assert s.REASONING_COOLDOWN_SECONDS == 90.0
    assert isinstance(s.REASONING_COOLDOWN_SECONDS, float)


def test_bool_override_coerced(tmp_path):
    s = _Settings()
    _write_override(tmp_path, "PROMPT_EVOLUTION_ENABLED", "false")
    apply_parameter_overrides(s, root=tmp_path)
    assert s.PROMPT_EVOLUTION_ENABLED is False


def test_unknown_param_skipped(tmp_path):
    s = _Settings()
    _write_override(tmp_path, "NOT_A_REAL_SETTING", 1)
    assert apply_parameter_overrides(s, root=tmp_path) == []


def test_bad_value_skipped_not_crash(tmp_path):
    s = _Settings()
    _write_override(tmp_path, "REASONING_COOLDOWN_SECONDS", "not-a-number")
    assert apply_parameter_overrides(s, root=tmp_path) == []
    assert s.REASONING_COOLDOWN_SECONDS == 60.0  # untouched


def test_malformed_json_skipped(tmp_path):
    d = tmp_path / PARAMETER_OVERRIDES_DIR
    d.mkdir(parents=True)
    (d / "broken.json").write_text("{not json")
    assert apply_parameter_overrides(_Settings(), root=tmp_path) == []
