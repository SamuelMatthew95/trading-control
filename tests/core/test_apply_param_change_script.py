"""Tests for scripts/apply_param_change.py — JSON-overrides file-IO wrapper.

The pure edit logic is covered in test_param_overrides; here we verify the script
reads/writes config/param_overrides.json correctly, treats a missing file as {},
emits JSON, and uses the exit codes the workflow relies on (0 = applied,
1 = refused).
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

_SCRIPT = pathlib.Path("scripts/apply_param_change.py")


def _load_main():
    spec = importlib.util.spec_from_file_location("apply_param_change", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod.main


def test_script_creates_file_when_missing(tmp_path, capsys):
    main = _load_main()
    f = tmp_path / "param_overrides.json"  # does not exist yet
    rc = main(
        ["--parameter", "SIGNAL_CONFIDENCE_MIN_GATE", "--value", "0.55", "--overrides-path", str(f)]
    )
    assert rc == 0
    data = json.loads(f.read_text())
    assert data["SIGNAL_CONFIDENCE_MIN_GATE"] == 0.55
    assert json.loads(capsys.readouterr().out.strip())["ok"] is True


def test_script_merges_into_existing(tmp_path):
    main = _load_main()
    f = tmp_path / "param_overrides.json"
    f.write_text('{"STOP_LOSS_PCT": 0.04}\n')
    rc = main(
        ["--parameter", "SIGNAL_CONFIDENCE_MIN_GATE", "--value", "0.55", "--overrides-path", str(f)]
    )
    assert rc == 0
    data = json.loads(f.read_text())
    assert data["STOP_LOSS_PCT"] == 0.04  # preserved
    assert data["SIGNAL_CONFIDENCE_MIN_GATE"] == 0.55  # added


def test_script_refuses_out_of_bounds_and_leaves_file(tmp_path, capsys):
    main = _load_main()
    f = tmp_path / "param_overrides.json"
    f.write_text("{}\n")
    rc = main(
        ["--parameter", "SIGNAL_CONFIDENCE_MIN_GATE", "--value", "0.99", "--overrides-path", str(f)]
    )
    assert rc == 1
    assert f.read_text() == "{}\n"  # untouched
    assert json.loads(capsys.readouterr().out.strip())["ok"] is False


def test_script_refuses_unlisted_parameter(tmp_path):
    main = _load_main()
    f = tmp_path / "param_overrides.json"
    f.write_text("{}\n")
    rc = main(["--parameter", "TOTALLY_FAKE", "--value", "2", "--overrides-path", str(f)])
    assert rc == 1
    assert f.read_text() == "{}\n"


def test_script_coerces_int_style_param(tmp_path):
    # All current allowlisted params are floats; verify a float param round-trips.
    main = _load_main()
    f = tmp_path / "param_overrides.json"
    rc = main(["--parameter", "STOP_LOSS_PCT", "--value", "0.04", "--overrides-path", str(f)])
    assert rc == 0
    assert json.loads(f.read_text())["STOP_LOSS_PCT"] == 0.04
