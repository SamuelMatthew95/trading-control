#!/usr/bin/env python3
"""Apply ONE parameter change to api/constants.py — the file-IO wrapper.

Layer in the GitOps loop:
    api/services/param_evolution.apply_param_change_to_source   (pure, tested)
        -> scripts/apply_param_change.py                        (this: file IO)
            -> .github/workflows/param-evolution-pr.yml         (git/gh IO)

Reads the constants file, applies the edit via the pure helper (which enforces
all safe-bound / type / uniqueness invariants), and writes it back. Prints a
JSON line so the workflow can build the PR title/body, and exits non-zero on any
refusal so the workflow skips that parameter instead of opening a junk PR.

Usage:
    python scripts/apply_param_change.py --parameter SIGNAL_CONFIDENCE_MIN_GATE --value 0.55
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from api.services.param_evolution import apply_param_change_to_source

_DEFAULT_CONSTANTS = "api/constants.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parameter", required=True, help="UPPER_SNAKE constant name")
    parser.add_argument("--value", required=True, help="proposed numeric value")
    parser.add_argument("--constants-path", default=_DEFAULT_CONSTANTS)
    args = parser.parse_args(argv)

    path = pathlib.Path(args.constants_path)
    if not path.is_file():
        print(json.dumps({"ok": False, "error": f"file not found: {path}"}))
        return 2

    source = path.read_text()
    result = apply_param_change_to_source(source, args.parameter, args.value)

    if not result.ok or result.new_source is None:
        print(json.dumps({"ok": False, "parameter": args.parameter, "error": result.error}))
        return 1

    path.write_text(result.new_source)
    print(
        json.dumps(
            {
                "ok": True,
                "parameter": result.parameter,
                "previous_value": result.previous_value,
                "new_value": result.new_value,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
