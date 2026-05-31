"""Tests for scripts/apply_param_change.py — the file-IO wrapper of the GitOps loop.

The pure edit logic is covered in test_param_evolution; here we verify the script
correctly reads/writes a file, emits JSON, and uses exit codes the workflow relies
on (0 = applied, 1 = refused, 2 = file missing).
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


_CONSTANTS = "from typing import Final\n\nSIGNAL_CONFIDENCE_MIN_GATE: Final[float] = 0.50\n"


def test_script_applies_and_writes(tmp_path, capsys):
    main = _load_main()
    f = tmp_path / "constants.py"
    f.write_text(_CONSTANTS)

    rc = main(
        [
            "--parameter",
            "SIGNAL_CONFIDENCE_MIN_GATE",
            "--value",
            "0.55",
            "--constants-path",
            str(f),
        ]
    )
    assert rc == 0
    assert "SIGNAL_CONFIDENCE_MIN_GATE: Final[float] = 0.55" in f.read_text()
    out = json.loads(capsys.readouterr().out.strip())
    assert out["ok"] is True
    assert out["previous_value"] == 0.50
    assert out["new_value"] == 0.55


def test_script_refuses_out_of_bounds_and_leaves_file(tmp_path, capsys):
    main = _load_main()
    f = tmp_path / "constants.py"
    f.write_text(_CONSTANTS)

    rc = main(
        ["--parameter", "SIGNAL_CONFIDENCE_MIN_GATE", "--value", "0.99", "--constants-path", str(f)]
    )
    assert rc == 1
    assert f.read_text() == _CONSTANTS  # untouched
    out = json.loads(capsys.readouterr().out.strip())
    assert out["ok"] is False
    assert out["error"]


def test_script_missing_file_exit_2(tmp_path, capsys):
    main = _load_main()
    rc = main(
        [
            "--parameter",
            "SIGNAL_CONFIDENCE_MIN_GATE",
            "--value",
            "0.55",
            "--constants-path",
            str(tmp_path / "nope.py"),
        ]
    )
    assert rc == 2
    out = json.loads(capsys.readouterr().out.strip())
    assert out["ok"] is False


def test_script_refuses_unlisted_parameter(tmp_path, capsys):
    main = _load_main()
    f = tmp_path / "constants.py"
    f.write_text("FOO: Final[int] = 1\n")
    rc = main(["--parameter", "FOO", "--value", "2", "--constants-path", str(f)])
    assert rc == 1
    assert f.read_text() == "FOO: Final[int] = 1\n"  # untouched
