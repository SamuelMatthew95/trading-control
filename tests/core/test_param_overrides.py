"""Tests for param_overrides — the SAFE, data-driven parameter override loader.

The learning loop edits config/param_overrides.json (plain data); the constants
loader applies it at startup. These prove a bad override degrades to "use the
default", never to a crash or an unsafe value — and that a good override actually
takes effect on api.constants.
"""

from __future__ import annotations

import importlib
import json

from api.services.param_overrides import (
    apply_param_override,
    load_overrides,
    sanitize_overrides,
)

# ---------------------------------------------------------------------------
# sanitize_overrides — drop anything unsafe, keep valid in-bounds entries
# ---------------------------------------------------------------------------


def test_sanitize_keeps_valid_drops_invalid():
    raw = {
        "SIGNAL_CONFIDENCE_MIN_GATE": 0.55,  # valid
        "STOP_LOSS_PCT": 0.99,  # out of bounds -> drop
        "TOTALLY_FAKE": 1.0,  # unknown -> drop
        "KELLY_FRACTION_SCALE": "0.3",  # numeric string -> kept, coerced
    }
    clean = sanitize_overrides(raw)
    assert clean["SIGNAL_CONFIDENCE_MIN_GATE"] == 0.55
    assert clean["KELLY_FRACTION_SCALE"] == 0.3
    assert "STOP_LOSS_PCT" not in clean
    assert "TOTALLY_FAKE" not in clean


def test_sanitize_non_dict_returns_empty():
    assert sanitize_overrides([]) == {}  # type: ignore[arg-type]
    assert sanitize_overrides("nope") == {}  # type: ignore[arg-type]


def test_sanitize_rejects_bool():
    assert "SIGNAL_CONFIDENCE_MIN_GATE" not in sanitize_overrides(
        {"SIGNAL_CONFIDENCE_MIN_GATE": True}
    )


# ---------------------------------------------------------------------------
# load_overrides — file IO, never raises
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_empty(tmp_path):
    assert load_overrides(tmp_path / "nope.json") == {}


def test_load_bad_json_returns_empty(tmp_path):
    f = tmp_path / "o.json"
    f.write_text("{ not valid json ")
    assert load_overrides(f) == {}


def test_load_valid_file(tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"SIGNAL_CONFIDENCE_MIN_GATE": 0.6, "BOGUS": 1}))
    loaded = load_overrides(f)
    assert loaded == {"SIGNAL_CONFIDENCE_MIN_GATE": 0.6}  # BOGUS dropped


# ---------------------------------------------------------------------------
# apply_param_override — pure JSON editor
# ---------------------------------------------------------------------------


def test_apply_adds_to_empty():
    ok, text, err = apply_param_override("{}", "SIGNAL_CONFIDENCE_MIN_GATE", 0.55)
    assert ok and err is None
    assert json.loads(text) == {"SIGNAL_CONFIDENCE_MIN_GATE": 0.55}
    assert text.endswith("\n")  # trailing newline for clean diffs


def test_apply_merges_and_sorts_keys():
    ok, text, _ = apply_param_override('{"STOP_LOSS_PCT": 0.04}', "KELLY_FRACTION_SCALE", 0.3)
    assert ok
    data = json.loads(text)
    assert data == {"STOP_LOSS_PCT": 0.04, "KELLY_FRACTION_SCALE": 0.3}
    # sort_keys => KELLY before STOP
    assert list(data.keys()) == ["KELLY_FRACTION_SCALE", "STOP_LOSS_PCT"]


def test_apply_refuses_out_of_bounds():
    ok, text, err = apply_param_override("{}", "SIGNAL_CONFIDENCE_MIN_GATE", 0.99)
    assert not ok and text is None and err


def test_apply_refuses_unknown_param():
    ok, _text, err = apply_param_override("{}", "FAKE", 1.0)
    assert not ok and err


def test_apply_refuses_noop():
    ok, _text, err = apply_param_override(
        '{"SIGNAL_CONFIDENCE_MIN_GATE": 0.55}', "SIGNAL_CONFIDENCE_MIN_GATE", 0.55
    )
    assert not ok
    assert "no change needed" in (err or "")


def test_apply_refuses_non_object_json():
    ok, _text, err = apply_param_override("[1,2,3]", "SIGNAL_CONFIDENCE_MIN_GATE", 0.55)
    assert not ok and err


# ---------------------------------------------------------------------------
# Integration: constants.py actually APPLIES a valid override at import
# ---------------------------------------------------------------------------


def test_constants_applies_override_at_import(tmp_path, monkeypatch):
    """A valid override file must change the published api.constants value when the
    module is re-imported — proving the loader is wired, not decorative."""
    f = tmp_path / "param_overrides.json"
    f.write_text(json.dumps({"SIGNAL_CONFIDENCE_MIN_GATE": 0.62}))
    monkeypatch.setenv("PARAM_OVERRIDES_PATH", str(f))

    from api import constants as _constants

    reloaded = importlib.reload(_constants)
    try:
        assert reloaded.SIGNAL_CONFIDENCE_MIN_GATE == 0.62
        assert reloaded.ACTIVE_PARAM_OVERRIDES.get("SIGNAL_CONFIDENCE_MIN_GATE") == 0.62
    finally:
        # Reload once more WITHOUT the env override so other tests see defaults.
        monkeypatch.delenv("PARAM_OVERRIDES_PATH", raising=False)
        importlib.reload(_constants)


def test_constants_ignores_bad_override_at_import(tmp_path, monkeypatch):
    """An out-of-bounds override must be ignored — the code default stands."""
    f = tmp_path / "param_overrides.json"
    f.write_text(json.dumps({"SIGNAL_CONFIDENCE_MIN_GATE": 9.99}))
    monkeypatch.setenv("PARAM_OVERRIDES_PATH", str(f))

    from api import constants as _constants

    reloaded = importlib.reload(_constants)
    try:
        assert reloaded.SIGNAL_CONFIDENCE_MIN_GATE == 0.50  # default, not 9.99
        assert "SIGNAL_CONFIDENCE_MIN_GATE" not in reloaded.ACTIVE_PARAM_OVERRIDES
    finally:
        monkeypatch.delenv("PARAM_OVERRIDES_PATH", raising=False)
        importlib.reload(_constants)
