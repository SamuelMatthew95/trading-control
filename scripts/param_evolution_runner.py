#!/usr/bin/env python3
"""Plan + execute parameter-evolution PRs — the tested core of the workflow.

The GitHub Action used to carry all this logic as inline shell+Python that never
runs in CI (pure guesswork). This module extracts it into real, unit-tested
functions so the risky parts — branch naming, idempotent skip, base-ref
resolution, command sequencing — are verified, not hoped.

Layering:
    apply_param_override         (api/services/param_overrides, pure, tested)
      -> apply_param_change.py   (file IO on config/param_overrides.json, tested)
        -> param_evolution_runner (THIS: planning + git/gh orchestration, tested)
          -> param-evolution-pr.yml (thin shell: just runs this)

``plan_branch_name`` / ``resolve_base_ref`` / ``should_skip_existing`` are pure
and fully tested. ``run_evolution`` wires them to injected runner callables, so a
test drives the whole sequence with a fake runner — no real git/gh/network.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

# A command runner returns (returncode, stdout, stderr). Injected so tests can
# drive run_evolution without touching git/gh/the network.
Runner = Callable[[Sequence[str]], "tuple[int, str, str]"]

_SAFE_BRANCH_RE = re.compile(r"[^A-Za-z0-9._-]+")


def plan_branch_name(parameter: str) -> str:
    """Deterministic branch per parameter so re-runs map to the same PR (idempotent).

    Sanitizes anything outside the git-ref-safe set, so even a malformed parameter
    can never produce an injection or an invalid ref.
    """
    safe = _SAFE_BRANCH_RE.sub("-", parameter.strip()).strip("-_.") or "unknown"
    return f"param-evolution/{safe}"


def resolve_base_ref(env: dict[str, str] | None = None) -> str:
    """The base branch for the PR.

    ``GITHUB_BASE_REF`` is only set on pull_request events — empty on schedule /
    workflow_dispatch (the actual triggers here). Fall back to GITHUB_DEFAULT_BRANCH
    then "main", so we never call ``gh pr create --base ''``. (This was a real bug
    in the first cut of the inline workflow.)
    """
    env = env if env is not None else dict(os.environ)
    for key in ("GITHUB_BASE_REF", "GITHUB_DEFAULT_BRANCH"):
        val = (env.get(key) or "").strip()
        if val:
            return val
    return "main"


def should_skip_existing(pr_list_json: str) -> bool:
    """True if ``gh pr list --json number`` shows an open PR already exists."""
    try:
        data = json.loads(pr_list_json or "[]")
    except (json.JSONDecodeError, TypeError):
        return False
    return bool(data)


@dataclass
class EvolutionResult:
    opened: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)


def _valid_item(item: dict) -> bool:
    return bool(item.get("parameter")) and item.get("proposed_value") is not None


def run_evolution(
    items: list[dict],
    run: Runner,
    *,
    base_ref: str | None = None,
    script_path: str = "scripts/apply_param_change.py",
) -> EvolutionResult:
    """Open one PR per validated item, idempotently. Pure orchestration over ``run``.

    For each item: skip if a PR for its branch is already open; else branch off
    base, apply the edit via the script (skip on refusal — out-of-bounds/unknown),
    commit, push, and open a PR. Returns a structured tally for the workflow log.
    """
    result = EvolutionResult()
    base = base_ref or resolve_base_ref()

    for item in items:
        if not _valid_item(item):
            continue
        parameter = str(item["parameter"])
        value = item["proposed_value"]
        reason = str(item.get("reason") or "")
        branch = plan_branch_name(parameter)

        rc, out, _ = run(
            ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number"]
        )
        if rc == 0 and should_skip_existing(out):
            result.skipped.append(parameter)
            continue

        run(["git", "checkout", "-B", branch, base])
        rc, out, err = run(
            ["python3", script_path, "--parameter", parameter, "--value", str(value)]
        )
        if rc != 0:
            result.refused.append(parameter)
            run(["git", "checkout", base])
            continue

        try:
            info = json.loads(out.strip())
            prev, new = info.get("previous_value"), info.get("new_value")
        except (json.JSONDecodeError, TypeError):
            prev, new = None, value

        title = f"chore(params): {parameter} {prev} -> {new} (learning loop)"
        # The bot edits the plain-DATA overrides file, never source code.
        run(["git", "add", "config/param_overrides.json"])
        run(["git", "commit", "-m", title])
        rc, _, err = run(["git", "push", "-f", "origin", branch])
        if rc != 0:
            result.refused.append(parameter)
            run(["git", "checkout", base])
            continue

        body = _pr_body(parameter, prev, new, reason)
        run(
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                body,
                "--head",
                branch,
                "--base",
                base,
            ]
        )
        result.opened.append(parameter)
        run(["git", "checkout", base])

    return result


def _pr_body(parameter: str, prev: object, new: object, reason: str) -> str:
    return (
        "## Automated parameter-evolution proposal\n\n"
        f"The learning loop proposes overriding **`{parameter}`** via "
        "`config/param_overrides.json` (plain data — no source code is edited):\n\n"
        f"| | value |\n|---|---|\n| current | `{prev}` |\n| proposed | `{new}` |\n\n"
        f"**Reason:** {reason or '_none provided_'}\n\n"
        "Generated from a `pr_request` artifact emitted by `ProposalApplier`. The value is "
        "within the safe bounds enforced by `api/services/param_evolution.PARAM_BOUNDS`, and "
        "is re-validated by the constants loader at startup (a bad value falls back to the "
        "code default). **Review the trade-off before merging** — merging deploys the change "
        "on next restart.\n\n"
        "---\n🤖 Auto-opened by the Parameter Evolution workflow."
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint used by the workflow: reads pending.json, runs the plan."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pending-file", required=True)
    args = parser.parse_args(argv)

    items = json.load(open(args.pending_file)).get("items", [])

    def _run(cmd: Sequence[str]) -> tuple[int, str, str]:
        p = subprocess.run(list(cmd), text=True, capture_output=True)
        return p.returncode, p.stdout, p.stderr

    result = run_evolution(items, _run)
    print(
        json.dumps(
            {
                "opened": result.opened,
                "skipped": result.skipped,
                "refused": result.refused,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
