"""Proposal implementation briefs — make a proposal Claude-Code-ready.

A learning-loop proposal that needs human/Claude design (CODE_CHANGE /
REGIME_ADJUSTMENT / NEW_AGENT) used to be filed as a *thin* GitHub issue: a
one-line description plus a raw JSON dump of the proposal content. That is the
"proposals are bullshit, not helpful links" complaint — there was nothing for
Claude Code (or a human) to act on, and proposals fired on a single trade with
no evidence framing (issue #341: "disable model X in the risk-off regime" off
ONE -4.05 trade).

This module turns a proposal + the evidence behind it into a complete,
**Claude-Code-ready implementation brief** (the GitHub issue body): the problem,
the *measured* evidence with an honest strength tier, the repo subsystems to
look at, the mechanism OPTIONS (so the implementer picks instead of guessing),
acceptance criteria, the project's hard invariants, and a ready-to-paste Claude
Code prompt.

Evidence is **tiered, never gated**. A small-sample proposal is not dropped —
the loop closes only a handful of trades a day, so a hard minimum would just
empty the queue. Instead it is labelled ``preliminary`` and framed as a WATCH
ITEM ("monitor, do NOT ship a behavioural change on this alone; here is the
evidence that would make it actionable"), exactly the verdict the #341 triage
asked for — now baked into the proposal itself rather than left for a human to
discover and reject.

Pure: no IO, no Redis, no network. Fully unit-tested.
"""

from __future__ import annotations

from typing import Any

from api.constants import (
    PROPOSAL_SOLID_EVIDENCE_TRADES,
    FieldName,
    ProposalType,
)

# Evidence strength tiers — labelling only, NEVER a gate. ``solid`` needs both a
# meaningful sample AND a backtest verdict; ``emerging`` is a real but young
# pattern worth a default-off experiment; ``preliminary`` is a single-trade-ish
# fluke (the #341 n=1 case) surfaced as a watch item, not a go-ahead.
TIER_PRELIMINARY = "preliminary"
TIER_EMERGING = "emerging"
TIER_SOLID = "solid"
# Below this sample size a pattern is too thin to act on; at/above it (but below
# the solid bar) it is "emerging". Module-local presentation detail.
_EMERGING_EVIDENCE_TRADES = 5

# Coarse THEMES detected from a proposal (its type + a keyword scan), used to
# point the brief at the right repo subsystems and the right mechanism menu.
# Some keys (regime/tool/parameter/execution/prompt) collide with FieldName
# values — they are theme identifiers, NOT payload fields, so this file is listed
# in SQL_BIND_HEAVY_FILES exactly like param_evolution.HYPOTHESIS_PARAM_MAP.
_THEME_MODEL_GOVERNANCE = "model_governance"
_THEME_REGIME = "regime"
_THEME_TOOL = "tool"
_THEME_PROMPT = "prompt"
_THEME_NEW_AGENT = "new_agent"
_THEME_EXECUTION = "execution"
_THEME_PARAMETER = "parameter"
# The system proposing an extension to ITSELF — a new automated detector /
# proposal type for a recurring pattern it currently has no dedicated response to.
_THEME_SELF_EXTENSION = "self_extension"
_THEME_DEFAULT = "default"

# Keyword tuples (NOT dict keys / membership literals — kept guardrail-clean).
_MODEL_WORDS = ("model", "llm", "provider", "gemini", "claude", "groq", "anthropic")
_REGIME_WORDS = ("regime", "macro", "risk-off", "risk_off", "risk-on", "risk_on", "bearish")
_TOOL_WORDS = ("tool", "perception", "indicator")
_PROMPT_WORDS = ("prompt", "directive", "reasoning instruction")
_EXECUTION_WORDS = (
    "execution",
    "order",
    "fill",
    "slippage",
    "stop-loss",
    "take-profit",
    "entry gate",
)
_SELF_EXTENSION_WORDS = (
    "self-extension",
    "new observer",
    "new detector",
    "proposal taxonomy",
    "automate the response",
)

_AFFECTED_AREA: dict[str, list[str]] = {
    _THEME_MODEL_GOVERNANCE: [
        "api/services/llm_router.py — model selection / routing + the fallback chain",
        "api/services/decision_policy.py — how the macro regime weights a decision",
        "api/services/market_intel.py — read_cached_macro_regime (the regime signal source)",
        "api/constants.py — RISK_OFF_* thresholds and model identifiers",
    ],
    _THEME_REGIME: [
        "api/services/decision_policy.py — regime → directional weighting",
        "api/services/execution/execution_engine.py — _check_pre_execution_gates (regime gate)",
        "api/constants.py — RISK_OFF_* execution/risk thresholds",
        "api/services/agents/risk_guardian.py — regime-aware stop / take-profit / daily-loss",
    ],
    _THEME_TOOL: [
        "api/services/tool_registry.py — tool enable/disable + alpha attribution",
        "api/services/agents/reasoning_agent.py — which tools the prompt offers per node",
    ],
    _THEME_PROMPT: [
        "api/services/agents/prompts.py — the prompt templates",
        "api/services/prompt_store.py — the versioned adaptive directive beneath the constitution",
    ],
    _THEME_NEW_AGENT: [
        "backtest/strategies.py — register the strategy the agent trades",
        "api/services/challenger_spawner.py — spawn a shadow challenger (config, no deploy)",
        "api/startup.py::_build_agents — wiring an always-on agent (mind the Redis-pool invariant)",
    ],
    _THEME_EXECUTION: [
        "api/services/execution/execution_engine.py — order gates + fills",
        "api/services/agents/risk_guardian.py — stop-loss / take-profit / daily-loss",
    ],
    _THEME_PARAMETER: [
        "api/services/param_evolution.py — PARAM_BOUNDS allowlist + validation",
        "api/constants.py — the tunable constant itself",
    ],
    _THEME_SELF_EXTENSION: [
        "api/services/agents/system_architect.py — add a new `_*_observation` method to the pass",
        "api/services/proposal_brief.py — add the new theme's affected-area + mechanism menus",
        "api/constants.py::ProposalType + api/services/agents/proposal_applier.py — only if a "
        "genuinely new proposal TYPE (with its own handler) is warranted",
    ],
}
_DEFAULT_AFFECTED_AREA: list[str] = [
    "api/services/agents/ — the agent fleet (start from the producer named in the trace)",
    "api/constants.py — any new threshold/flag (never hardcode; FieldName for payload keys)",
    "api/config.py — a default-OFF feature flag when the change is behavioural",
]

_MECHANISM_OPTIONS: dict[str, list[str]] = {
    _THEME_MODEL_GOVERNANCE: [
        "Hard-disable the model for that regime in the router (most aggressive; least reversible).",
        "Down-weight the model's selection probability in that regime (reversible, preferred).",
        "Route to a fallback model in that regime, keeping the model available elsewhere.",
    ],
    _THEME_REGIME: [
        "Parameterise the behaviour behind a default-OFF flag in api/config.py.",
        "Tune the relevant RISK_OFF_* threshold in api/constants.py (bounds-checked).",
        "Add a guarded gate in execution_engine that only fires in the named regime; never gate exits.",
    ],
    _THEME_TOOL: [
        "Disable the tool in the ToolRegistry (the existing tool-governance path).",
        "Keep it enabled but down-weight its alpha so the prompt deprioritises it.",
        "Keep it and monitor — revisit once it has more graded calls.",
    ],
    _THEME_NEW_AGENT: [
        "Spawn it as a SHADOW challenger first (no live orders) and promote only on evidence.",
        "Add it as a config-only variant of an existing strategy if one fits.",
        "If it needs new code, scope the smallest strategy module that backtests cleanly.",
    ],
    _THEME_SELF_EXTENSION: [
        "Add a deterministic `_*_observation` method to SystemArchitect that detects this "
        "pattern and emits an evidence-tiered, briefed proposal (the cheapest, safest option).",
        "Add a new ProposalType + ProposalApplier handler only if the response is a distinct "
        "control-plane / routing action the existing types cannot express.",
        "Encode it as a reflection rule / recommendation if it is per-trade rather than systemic.",
    ],
}
_DEFAULT_MECHANISMS: list[str] = [
    "Parameterise the behaviour behind a default-OFF flag so nothing changes until opted in.",
    "Tune an existing allowlisted constant within its safe bounds (api/services/param_evolution.py).",
    "Add a guarded gate that fails safe (degrades to current behaviour on any uncertainty).",
]

# The hard invariants any PR in this repo must hold — handed to Claude Code so a
# generated change respects the house rules instead of tripping CI.
_PROJECT_CONSTRAINTS: list[str] = [
    "Every payload / DB-row / Redis dict key goes through the FieldName StrEnum "
    "(api/constants.py) — no raw string keys (CI-enforced).",
    "New writes use schema_version='v3'; agent_runs/events have INTEGER pks (INSERT ... RETURNING id).",
    "Redis keys, TTLs, agent names, thresholds and flags live in api/constants.py / api/config.py — never hardcode.",
    "The trading constitution is immutable: capital preservation outranks profit; "
    "a change can never weaken a safety / risk rule, and exits are never blocked.",
    "Default-neutral: ship any behavioural change behind a flag that is OFF by default.",
    "Imports at module top only (ruff PLC0415); log via log_structured (no print / logger.*).",
    "CI must pass: ruff check . --fix && ruff format --check . && "
    "pytest tests/core tests/api && pytest tests/integration. Add a regression test.",
    "Add a docs/troubleshooting/<subsystem>.md entry in the same commit as the fix.",
]


def classify_evidence(sample_size: int, *, has_backtest: bool) -> str:
    """Label evidence strength. Pure; NEVER blocks — only frames the brief."""
    if sample_size >= PROPOSAL_SOLID_EVIDENCE_TRADES and has_backtest:
        return TIER_SOLID
    if sample_size >= _EMERGING_EVIDENCE_TRADES:
        return TIER_EMERGING
    return TIER_PRELIMINARY


def evidence_is_solid(evidence: dict[str, Any]) -> bool:
    """True when the evidence block clears the ``solid`` bar."""
    sample = _int(evidence.get(FieldName.SAMPLE_SIZE))
    return (
        classify_evidence(sample, has_backtest=bool(evidence.get(FieldName.BACKTEST))) == TIER_SOLID
    )


def evidence_from_reflection(reflection: dict[str, Any]) -> dict[str, Any]:
    """Assemble the evidence block a brief reads from a reflection payload.

    The reflection already carries the deterministic quant sample
    (``trades_analyzed``), win rate, per-model performance and regime — this just
    shapes them into the common evidence dict the brief + tier classifier use.
    """
    sample = _int(reflection.get(FieldName.TRADES_ANALYZED)) or _int(
        reflection.get(FieldName.FILLS_ANALYZED)
    )
    backtest = reflection.get(FieldName.BACKTEST)
    regime_edge = reflection.get(FieldName.REGIME_EDGE) or {}
    regime = regime_edge.get(FieldName.CURRENT_REGIME) if isinstance(regime_edge, dict) else None
    evidence: dict[str, Any] = {
        FieldName.SAMPLE_SIZE: sample,
        FieldName.WIN_RATE: reflection.get(FieldName.WIN_RATE),
        FieldName.AVG_RETURN: reflection.get(FieldName.AVG_RETURN),
        FieldName.REGIME: regime,
        FieldName.MODEL_PERFORMANCE: reflection.get(FieldName.MODEL_PERFORMANCE) or [],
        FieldName.BACKTEST: backtest,
    }
    evidence[FieldName.EVIDENCE_SUFFICIENT] = evidence_is_solid(evidence)
    return evidence


def build_implementation_brief(
    *,
    proposal_type: str,
    summary: str,
    content: dict[str, Any],
    evidence: dict[str, Any] | None = None,
    category: str | None = None,
) -> str:
    """Return a Claude-Code-ready markdown implementation brief.

    Robust to sparse input — a brief is always produced (an empty evidence block
    just yields the ``preliminary`` tier). The returned string is the GitHub
    issue body and is self-contained.
    """
    evidence = evidence or {}
    theme = _detect_theme(proposal_type, category, summary, content)
    sample = _int(evidence.get(FieldName.SAMPLE_SIZE))
    tier = classify_evidence(sample, has_backtest=bool(evidence.get(FieldName.BACKTEST)))
    headline = summary.strip() or proposal_type.replace("_", " ")

    lines: list[str] = [
        f"## Proposal: {headline}",
        "",
        f"_Auto-generated implementation brief — proposal type `{proposal_type}`, evidence "
        f"tier **{tier}**. Hand this to Claude Code (it has full repo context) to open a PR._",
        "",
        _recommendation_banner(tier, sample),
        "",
        "### Problem",
        _problem_text(content, headline),
        "",
        "### Evidence (measured)",
        *_evidence_lines(evidence),
        "",
        "### Affected area (where to look first)",
        *(f"- {hint}" for hint in _AFFECTED_AREA.get(theme, _DEFAULT_AFFECTED_AREA)),
        "",
        "### Mechanism options (choose one — do not guess)",
        *(
            f"{i}. {opt}"
            for i, opt in enumerate(_MECHANISM_OPTIONS.get(theme, _DEFAULT_MECHANISMS), start=1)
        ),
        "",
        "### Acceptance criteria",
        *(f"- {crit}" for crit in _acceptance_criteria(tier)),
        "",
        "### Constraints (project invariants — must hold)",
        *(f"- {c}" for c in _PROJECT_CONSTRAINTS),
        "",
        "### Ready-to-paste Claude Code prompt",
        "```",
        _claude_prompt(proposal_type, headline, theme, tier),
        "```",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _detect_theme(
    proposal_type: str, category: str | None, summary: str, content: dict[str, Any]
) -> str:
    """Map a proposal to a coarse theme for the affected-area + mechanism menus."""
    if proposal_type == ProposalType.NEW_AGENT:
        return _THEME_NEW_AGENT
    if proposal_type == ProposalType.TOOL_GOVERNANCE:
        return _THEME_TOOL
    if proposal_type == ProposalType.PROMPT_EVOLUTION:
        return _THEME_PROMPT
    if proposal_type == ProposalType.PARAMETER_CHANGE:
        return _THEME_PARAMETER

    text = " ".join(
        str(part)
        for part in (
            category,
            summary,
            content.get(FieldName.DESCRIPTION),
            content.get(FieldName.REASON),
        )
        if part
    ).lower()

    # The system proposing to extend its OWN automation comes first — it can
    # mention a model/regime as the example pattern, but the change is to the
    # proposal pipeline, not the model.
    if _has_any(text, _SELF_EXTENSION_WORDS):
        return _THEME_SELF_EXTENSION
    # A named LLM model (optionally alongside a regime — the #341 case) is a
    # model-governance proposal: surface the disable / down-weight / fallback
    # mechanism menu, not a generic regime tweak.
    if _has_any(text, _MODEL_WORDS):
        return _THEME_MODEL_GOVERNANCE
    if _has_any(text, _REGIME_WORDS):
        return _THEME_REGIME
    if _has_any(text, _TOOL_WORDS):
        return _THEME_TOOL
    if _has_any(text, _PROMPT_WORDS):
        return _THEME_PROMPT
    if _has_any(text, _EXECUTION_WORDS):
        return _THEME_EXECUTION
    # A regime_adjustment with no clearer signal is still regime-shaped.
    if proposal_type == ProposalType.REGIME_ADJUSTMENT:
        return _THEME_REGIME
    return _THEME_DEFAULT


def _recommendation_banner(tier: str, sample: int) -> str:
    if tier == TIER_SOLID:
        return (
            f"✅ **Ready to implement.** Sample is statistically meaningful (n={sample}) and a "
            "measured backtest verdict is attached below."
        )
    if tier == TIER_EMERGING:
        return (
            f"🟡 **Emerging signal (n={sample}).** A real but young pattern — implement behind a "
            "default-OFF flag and keep gathering data before enabling it."
        )
    return (
        f"⚠️ **Preliminary — small sample (n={sample}).** Treat this as a WATCH ITEM, not a "
        "go-ahead: do NOT ship a behavioural change on this alone. Monitor and re-evaluate once "
        f"≥{PROPOSAL_SOLID_EVIDENCE_TRADES} trades (with a backtest verdict) confirm it. The brief "
        "below readies the mechanism IF the evidence firms up."
    )


def _problem_text(content: dict[str, Any], headline: str) -> str:
    description = str(
        content.get(FieldName.DESCRIPTION) or content.get(FieldName.REASON) or headline
    ).strip()
    recommendation = content.get(FieldName.RECOMMENDATION)
    if recommendation:
        return f"{description}\n\nObserved recommendation: {recommendation}"
    return description


def _evidence_lines(evidence: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    sample = _int(evidence.get(FieldName.SAMPLE_SIZE))
    lines.append(f"- Sample size (trades analysed): **{sample}**")

    win_rate = evidence.get(FieldName.WIN_RATE)
    if win_rate is not None:
        lines.append(f"- Win rate: {_pct(win_rate)}")
    avg_return = evidence.get(FieldName.AVG_RETURN)
    if avg_return is not None:
        lines.append(f"- Avg return: {avg_return}")
    regime = evidence.get(FieldName.REGIME)
    if regime:
        lines.append(f"- Macro regime: {regime}")

    backtest = evidence.get(FieldName.BACKTEST)
    if isinstance(backtest, dict) and backtest:
        rendered = ", ".join(f"{key}={value}" for key, value in backtest.items())
        lines.append(f"- Backtest verdict (ReplayHarness): {rendered}")
    else:
        lines.append("- Backtest verdict: _none attached — required before a behavioural change_")

    models = evidence.get(FieldName.MODEL_PERFORMANCE)
    if isinstance(models, list) and models:
        lines.append("- Per-model performance:")
        for row in models:
            if not isinstance(row, dict):
                continue
            name = row.get(FieldName.MODEL_USED) or "unknown"
            pnl = row.get(FieldName.TOTAL_PNL)
            wr = row.get(FieldName.WIN_RATE)
            count = row.get(FieldName.TRADE_COUNT)
            lines.append(f"  - `{name}` — pnl={pnl}, win_rate={_pct(wr)}, trades={count}")
    return lines


def _acceptance_criteria(tier: str) -> list[str]:
    base = [
        "Change is default-neutral: a new flag is OFF by default / no behaviour changes until opted in.",
        "Exits and de-risking are NEVER blocked by a new entry-side gate.",
        "tests/core, tests/api and tests/integration are green; a regression test that "
        "would have caught the original problem is added.",
        "A docs/troubleshooting/<subsystem>.md entry documents the change in the same commit.",
    ]
    if tier == TIER_PRELIMINARY:
        return [
            "DO NOT change behaviour yet — first confirm the pattern holds over more trades "
            f"(target ≥{PROPOSAL_SOLID_EVIDENCE_TRADES}) WITH an attached backtest verdict "
            "(win rate / PnL / Sharpe / false-positive rate). Only once confirmed:",
            *base,
        ]
    return base


def _claude_prompt(proposal_type: str, headline: str, theme: str, tier: str) -> str:
    first_area = _AFFECTED_AREA.get(theme, _DEFAULT_AFFECTED_AREA)[0]
    # Preliminary proposals get a leading caveat sentence; stronger evidence goes
    # straight to the action so the two read as grammatical, distinct prompts.
    lead = (
        "The evidence is PRELIMINARY: first verify the pattern holds over more trades (with a "
        "backtest verdict) before changing any behaviour, and close it if it does not hold. "
        if tier == TIER_PRELIMINARY
        else ""
    )
    return (
        f"In the trading-control repo, work the following {proposal_type} proposal: {headline}. "
        f"{lead}Choose ONE of the mechanism options in the issue and implement it behind a "
        f"default-OFF flag. Start from {first_area}. "
        "Follow the repo invariants (FieldName enum for all payload keys, schema_version='v3', "
        "constants/flags in api/constants.py & api/config.py, the immutable trading constitution, "
        "structured logging). Run the full CI (ruff check . --fix; ruff format --check .; "
        "pytest tests/core tests/api; pytest tests/integration), add a regression test, update "
        "docs/troubleshooting, then open a pull request describing the mechanism you chose and why."
    )


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%" if abs(float(value)) <= 1.0 else f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "n/a"
