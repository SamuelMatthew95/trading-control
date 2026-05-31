#!/usr/bin/env python3
"""Apply ONE parameter change to config/param_overrides.json — the file-IO wrapper.

Layer in the GitOps loop:
    api/services/param_overrides.apply_param_override   (pure, tested)
        -> scripts/apply_param_change.py                (this: file IO)
            -> .github/workflows/param-evolution-pr.yml (git/gh IO)

The bot edits a plain-DATA JSON file, never source code: a malformed or
out-of-bounds value is refused here, and even if a bad value somehow landed, the
constants loader validates it again and falls back to the code default — so a bad
artifact can never break the running app. The reviewed PR diff is one JSON line.

Reads the overrides JSON (treating a missing file as ``{}``), applies the edit via
the pure helper, writes it back. Prints a JSON line so the workflow can build the
PR body, and exits non-zero on any refusal so the workflow skips that parameter.

Usage:
    python scripts/apply_param_change.py --parameter SIGNAL_CONFIDENCE_MIN_GATE --value 0.55
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from api.services.param_overrides import DEFAULT_OVERRIDES_PATH, apply_param_override


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parameter", required=True, help="UPPER_SNAKE constant name")
    parser.add_argument("--value", required=True, help="proposed numeric value")
    parser.add_argument("--overrides-path", default=DEFAULT_OVERRIDES_PATH)
    args = parser.parse_args(argv)

    path = pathlib.Path(args.overrides_path)
    # A missing overrides file is normal (first override ever) — start from "{}".
    raw_text = path.read_text() if path.is_file() else "{}"

    ok, new_text, error = apply_param_override(raw_text, args.parameter, args.value)
    if not ok or new_text is None:
        print(json.dumps({"ok": False, "parameter": args.parameter, "error": error}))
        return 1

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text)
    print(json.dumps({"ok": True, "parameter": args.parameter, "new_value": args.value}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
