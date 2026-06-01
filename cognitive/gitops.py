"""GITOPS — the Auto-PR creator. Behaviour changes ONLY through a reviewed PR.

A proposal that has cleared the backtest gate and the challenger is turned into a
pull-request PLAN here: a deterministic branch name, the exact config diff
(before/after per key), and a PR body that embeds the proposal, the challenger
verdict, and the in-sample + out-of-sample backtest evidence. Nothing is
auto-merged — a human (or an explicit auto-merge policy) merges, and only the
merge changes the running config on the next load.

Config application is a PURE text transform (mirroring
``api/services/param_overrides.apply_param_override``): it takes the current JSON
text, applies the proposal, re-validates against the safe bounds, and emits
canonical sorted JSON so the PR diff is minimal and reviewable. A proposal that
would produce an out-of-bounds config is refused here, before any PR exists.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from cognitive.config import WEIGHT_KEYS, CognitiveConfig, clamp_weight, validate_config_dict
from cognitive.proposal import Proposal, ProposalType

BRANCH_PREFIX = "cognitive-evolution"


def slugify(text: str) -> str:
    """Lowercase, dash-separated slug safe for a git branch name."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def branch_name(proposal: Proposal) -> str:
    """Deterministic, idempotent branch name for a proposal."""
    return f"{BRANCH_PREFIX}/{slugify(proposal.target)}-{slugify(str(proposal.new_value))}"


def apply_proposal_to_config(config: CognitiveConfig, proposal: Proposal) -> CognitiveConfig | None:
    """Apply a config-targeting proposal, bumping the version. None if N/A or unsafe.

    Only WEIGHT_CHANGE and RISK_CHANGE map onto ``cognitive_config.json``; prompt
    / tool / feature / backtest changes target other files and return None here.
    """
    data = config.to_dict()
    if proposal.proposal_type == ProposalType.WEIGHT_CHANGE.value:
        signal = proposal.target.split(".")[-1]
        if signal not in WEIGHT_KEYS:
            return None
        data["weights"][signal] = clamp_weight(float(proposal.new_value))
    elif proposal.proposal_type == ProposalType.RISK_CHANGE.value:
        key = proposal.target.split(".")[-1]
        if key not in data["risk"]:
            return None
        data["risk"][key] = float(proposal.new_value)
    else:
        return None

    data["version"] = config.version + 1
    if validate_config_dict(data):
        return None
    return CognitiveConfig.from_dict(data)


def apply_to_config_text(raw_text: str, proposal: Proposal) -> tuple[bool, str | None, str | None]:
    """Pure text transform: current JSON -> new canonical JSON. (ok, text, error)."""
    try:
        current = json.loads(raw_text) if raw_text.strip() else {}
    except json.JSONDecodeError as exc:
        return False, None, f"invalid JSON: {exc}"
    if validate_config_dict(current):
        return False, None, "current config is not valid"
    updated = apply_proposal_to_config(CognitiveConfig.from_dict(current), proposal)
    if updated is None:
        return False, None, "proposal does not apply to the config file or is out of bounds"
    new_text = json.dumps(updated.to_dict(), indent=2, sort_keys=True) + "\n"
    if new_text == raw_text:
        return False, None, "proposal produces no change"
    return True, new_text, None


def config_diff(
    old: dict[str, Any], new: dict[str, Any], *, prefix: str = ""
) -> list[dict[str, Any]]:
    """Flattened per-key diff of two nested config dicts (changed leaves only)."""
    changes: list[dict[str, Any]] = []
    keys = sorted(set(old) | set(new))
    for key in keys:
        path = f"{prefix}{key}"
        old_value = old.get(key)
        new_value = new.get(key)
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            changes.extend(config_diff(old_value, new_value, prefix=f"{path}."))
        elif old_value != new_value:
            changes.append({"path": path, "old": old_value, "new": new_value})
    return changes


@dataclass(frozen=True)
class PullRequestPlan:
    """A ready-to-open PR. No auto-merge — the merge is a separate human/policy step."""

    branch: str
    base_ref: str
    title: str
    body: str
    diff: list[dict[str, Any]]
    config_before: dict[str, Any]
    config_after: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": "pr_request",
            "branch": self.branch,
            "base_ref": self.base_ref,
            "title": self.title,
            "body": self.body,
            "diff": list(self.diff),
            "config_before": dict(self.config_before),
            "config_after": dict(self.config_after),
            "auto_merge": False,
        }


def _metrics_block(label: str, delta: Any) -> str:
    """Render one baseline-vs-candidate backtest delta as a markdown block."""
    baseline = delta.baseline
    candidate = delta.candidate
    return "\n".join(
        [
            f"**{label}**",
            "",
            "| metric | baseline | candidate | delta |",
            "| --- | --- | --- | --- |",
            f"| return % | {baseline.total_return_pct} | {candidate.total_return_pct} "
            f"| {delta.pnl_delta:+} |",
            f"| sharpe | {baseline.sharpe} | {candidate.sharpe} | {delta.sharpe_delta:+} |",
            f"| max drawdown % | {baseline.max_drawdown_pct} | {candidate.max_drawdown_pct} "
            f"| {delta.drawdown_delta:+} |",
            f"| false-positive rate | {baseline.false_positive_rate} "
            f"| {candidate.false_positive_rate} | {delta.false_positive_rate_delta:+} |",
            "",
        ]
    )


def build_pull_request(
    proposal: Proposal,
    verdict: Any,
    in_sample: Any,
    out_sample: Any,
    config_before: CognitiveConfig,
    config_after: CognitiveConfig,
    *,
    base_ref: str = "main",
) -> PullRequestPlan:
    """Assemble the PR plan with the full evidence trail in the body."""
    before = config_before.to_dict()
    after = config_after.to_dict()
    diff = config_diff(before, after)
    title = (
        f"cognitive: {proposal.proposal_type} {proposal.target} "
        f"({proposal.old_value} -> {proposal.new_value})"
    )
    diff_lines = "\n".join(
        f"- `{change['path']}`: {change['old']} -> {change['new']}" for change in diff
    )
    body = "\n".join(
        [
            "## Proposal",
            f"- **Type:** {proposal.proposal_type}",
            f"- **Target:** `{proposal.target}`",
            f"- **Reason:** {proposal.reason}",
            f"- **Expected impact:** {proposal.expected_impact}",
            "",
            "## Config diff",
            diff_lines or "_(no leaf changes)_",
            "",
            "## Challenger verdict",
            f"- **Decision:** {'APPROVE' if verdict.approved else 'REJECT'}",
            f"- **Risk score:** {verdict.risk_score}",
            *[f"- {reason}" for reason in verdict.reasons],
            "",
            "## Backtest evidence",
            _metrics_block("In-sample", in_sample),
            _metrics_block("Out-of-sample", out_sample),
            "> NO auto-merge. Behaviour changes only after this PR is reviewed and merged.",
        ]
    )
    return PullRequestPlan(
        branch=branch_name(proposal),
        base_ref=base_ref,
        title=title,
        body=body,
        diff=diff,
        config_before=before,
        config_after=after,
    )
