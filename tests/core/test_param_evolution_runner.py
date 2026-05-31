"""Tests for scripts/param_evolution_runner — the tested core of the PR workflow.

This is the logic that used to live as un-runnable inline shell in the workflow
YAML (pure guesswork). Here a FAKE runner drives the full sequence so branch
naming, idempotent skip, base-ref fallback, refusal handling, and command
ordering are all verified without git/gh/network.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

_SCRIPT = pathlib.Path("scripts/param_evolution_runner.py")


def _load():
    spec = importlib.util.spec_from_file_location("param_evolution_runner", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # Register before exec so dataclasses can resolve __module__ (else introspection
    # hits sys.modules[None] and raises AttributeError at collection time).
    sys.modules["param_evolution_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_plan_branch_name_deterministic_and_safe():
    assert R.plan_branch_name("SIGNAL_CONFIDENCE_MIN_GATE") == (
        "param-evolution/SIGNAL_CONFIDENCE_MIN_GATE"
    )
    # Same input -> same branch (idempotency depends on this).
    assert R.plan_branch_name("FOO") == R.plan_branch_name("FOO")


def test_plan_branch_name_sanitizes_injection():
    b = R.plan_branch_name("foo; rm -rf / && echo")
    assert " " not in b and ";" not in b and "/" not in b.split("param-evolution/")[1]
    assert b.startswith("param-evolution/")


def test_resolve_base_ref_prefers_base_then_default_then_main():
    assert R.resolve_base_ref({"GITHUB_BASE_REF": "release"}) == "release"
    assert R.resolve_base_ref({"GITHUB_DEFAULT_BRANCH": "trunk"}) == "trunk"
    assert R.resolve_base_ref({}) == "main"
    # The real bug: empty base ref on schedule/dispatch must NOT yield "".
    assert R.resolve_base_ref({"GITHUB_BASE_REF": ""}) == "main"


def test_should_skip_existing():
    assert R.should_skip_existing('[{"number": 7}]') is True
    assert R.should_skip_existing("[]") is False
    assert R.should_skip_existing("") is False
    assert R.should_skip_existing("not json") is False


# ---------------------------------------------------------------------------
# run_evolution — full sequence with a fake runner
# ---------------------------------------------------------------------------


class _FakeRunner:
    """Records every command; scriptable responses for gh pr list and the apply step."""

    def __init__(self, *, open_branches=(), apply_ok=True, push_ok=True, prev=0.5, new=0.55):
        self.calls: list[list[str]] = []
        self._open = set(open_branches)
        self._apply_ok = apply_ok
        self._push_ok = push_ok
        self._prev = prev
        self._new = new

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        if cmd[:3] == ["gh", "pr", "list"]:
            branch = cmd[cmd.index("--head") + 1]
            return (0, json.dumps([{"number": 1}] if branch in self._open else []), "")
        if cmd and cmd[0] == "python3" and "apply_param_change.py" in cmd[1]:
            if self._apply_ok:
                return (0, json.dumps({"previous_value": self._prev, "new_value": self._new}), "")
            return (1, json.dumps({"ok": False, "error": "out of bounds"}), "")
        if cmd[:2] == ["git", "push"]:
            return (0, "", "") if self._push_ok else (1, "", "rejected")
        return (0, "", "")

    def commands(self, head):
        return [c for c in self.calls if c[: len(head)] == head]


_ITEM = {"parameter": "SIGNAL_CONFIDENCE_MIN_GATE", "proposed_value": 0.55, "reason": "tune"}


def test_opens_pr_for_new_parameter():
    runner = _FakeRunner()
    res = R.run_evolution([_ITEM], runner, base_ref="main")
    assert res.opened == ["SIGNAL_CONFIDENCE_MIN_GATE"]
    assert res.skipped == [] and res.refused == []
    # A PR was actually created, on the right base.
    pr_create = runner.commands(["gh", "pr", "create"])
    assert len(pr_create) == 1
    assert "--base" in pr_create[0] and pr_create[0][pr_create[0].index("--base") + 1] == "main"


def test_skips_when_pr_already_open():
    runner = _FakeRunner(open_branches={"param-evolution/SIGNAL_CONFIDENCE_MIN_GATE"})
    res = R.run_evolution([_ITEM], runner, base_ref="main")
    assert res.skipped == ["SIGNAL_CONFIDENCE_MIN_GATE"]
    assert res.opened == []
    # Idempotency: no branch/commit/PR commands were issued.
    assert runner.commands(["gh", "pr", "create"]) == []
    assert runner.commands(["git", "commit"]) == []


def test_refuses_when_apply_fails_and_no_pr():
    runner = _FakeRunner(apply_ok=False)
    res = R.run_evolution([_ITEM], runner, base_ref="main")
    assert res.refused == ["SIGNAL_CONFIDENCE_MIN_GATE"]
    assert res.opened == []
    assert runner.commands(["gh", "pr", "create"]) == []
    # It must check out back to base after refusing.
    assert ["git", "checkout", "main"] in runner.calls


def test_refuses_when_push_fails():
    runner = _FakeRunner(push_ok=False)
    res = R.run_evolution([_ITEM], runner, base_ref="main")
    assert res.refused == ["SIGNAL_CONFIDENCE_MIN_GATE"]
    assert runner.commands(["gh", "pr", "create"]) == []


def test_invalid_items_ignored():
    runner = _FakeRunner()
    res = R.run_evolution(
        [{"parameter": "", "proposed_value": 1}, {"parameter": "X", "proposed_value": None}],
        runner,
        base_ref="main",
    )
    assert res.opened == [] and res.skipped == [] and res.refused == []
    assert runner.calls == []  # nothing attempted


def test_multiple_items_mixed_outcomes():
    # One new (open), one already-open (skip).
    runner = _FakeRunner(open_branches={"param-evolution/STOP_LOSS_PCT"})
    items = [
        {"parameter": "SIGNAL_CONFIDENCE_MIN_GATE", "proposed_value": 0.55},
        {"parameter": "STOP_LOSS_PCT", "proposed_value": 0.04},
    ]
    res = R.run_evolution(items, runner, base_ref="main")
    assert res.opened == ["SIGNAL_CONFIDENCE_MIN_GATE"]
    assert res.skipped == ["STOP_LOSS_PCT"]


def test_pr_create_uses_resolved_base_when_not_passed(monkeypatch):
    monkeypatch.setenv("GITHUB_BASE_REF", "")
    monkeypatch.setenv("GITHUB_DEFAULT_BRANCH", "develop")
    runner = _FakeRunner()
    R.run_evolution([_ITEM], runner)  # base_ref=None -> resolve from env
    pr_create = runner.commands(["gh", "pr", "create"])[0]
    assert pr_create[pr_create.index("--base") + 1] == "develop"
