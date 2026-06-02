"""Tool Registry — runtime tool-governance intelligence layer.

Implements the Runtime Tool Governance directive: the LLM must never see the
full tool catalog at once. Tools carry metadata (phase, alpha attribution,
latency, failure rate, state prerequisites, capability-graph unlocks) and the
runtime selects only the eligible subset for the current DAG node / regime /
portfolio state. The same metadata powers dead-tool detection and the operator
UI's tool-attribution panel.

Pure and in-process — mirrors the ``get_strategy_registry`` singleton pattern.
No DB, no Redis, no live capital.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from api.constants import (
    TOOL_BRACKET_ORDER,
    TOOL_CORRELATION_CHECK,
    TOOL_FLAG_CONFLUENCE_LOADED,
    TOOL_FLAG_RISK_APPROVED,
    TOOL_FLAG_THESIS_COMMITTED,
    TOOL_GET_IC_WEIGHTS,
    TOOL_MACRO_REGIME,
    TOOL_NEWS_SENTIMENT,
    TOOL_ORDER_BOOK_DEPTH,
    TOOL_QUERY_SIMILAR_TRADES,
    TOOL_REPLAY_REGRESSION,
    TOOL_RISK_CAGE,
    TOOL_SECTOR_CORRELATION,
    TOOL_STREAM_CONFLUENCE,
    TOOL_VWAP_EXECUTION,
    ToolPhase,
)

# Exponential-moving-average weight for telemetry updates. Recent calls matter
# more, but a single outlier can't swing a tool's score wholesale.
_EMA_ALPHA = 0.2


class ToolMetadata(BaseModel):
    """Everything the runtime knows about one tool.

    Telemetry fields (``alpha_score``, ``latency_ms``, ``failure_rate``) are
    EMA-updated by :meth:`ToolRegistry.record_call`; the seeded values are
    priors so the attribution panel is meaningful before live calls arrive.
    """

    name: str
    phase: ToolPhase
    description: str = ""
    enabled: bool = True
    # Telemetry / attribution
    alpha_score: float = 0.0
    latency_ms: float = 0.0
    failure_rate: float = 0.0
    call_count: int = 0
    success_count: int = 0
    # Gating
    required_state_flags: list[str] = Field(default_factory=list)
    # Capability graph: tools this one unlocks once it has run successfully.
    unlocks: list[str] = Field(default_factory=list)
    cache_ttl: int | None = None


class ToolSuggestion(BaseModel):
    """A non-binding governance hint about one tool, surfaced to the operator.

    The registry never mutates state to produce these — they are advice the UI
    renders ("which tools to keep, which to drop from the reasoning prompt") and
    the human approves. ``action`` is one of: disable, prioritize, review.
    """

    tool: str
    action: str
    severity: str  # info | warning
    reason: str


def _ema(prev: float, sample: float, *, count: int) -> float:
    """EMA that seeds from the first real sample instead of the prior."""
    if count <= 0:
        return sample
    return (1 - _EMA_ALPHA) * prev + _EMA_ALPHA * sample


class ToolRegistry:
    """In-process registry of tools, their telemetry, and selection rules."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolMetadata] = {}

    # -- registration --
    def register(self, meta: ToolMetadata) -> ToolMetadata:
        self._tools[meta.name] = meta
        return meta

    def register_many(self, metas: list[ToolMetadata]) -> None:
        for meta in metas:
            self.register(meta)

    def get(self, name: str) -> ToolMetadata | None:
        return self._tools.get(name)

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Enable/disable a tool by name. Returns True if the tool exists and its
        state changed — used by the ProposalApplier to action an approved
        TOOL_GOVERNANCE proposal (e.g. disable a negative-alpha tool)."""
        tool = self._tools.get(name)
        if tool is None or tool.enabled == enabled:
            return False
        tool.enabled = enabled
        return True

    def all_tools(self) -> list[ToolMetadata]:
        return list(self._tools.values())

    # -- selection (the governance core) --
    def select_tools(
        self,
        phase: ToolPhase,
        *,
        available_state_flags: frozenset[str] | set[str] | None = None,
        max_latency_ms: float | None = None,
        min_alpha: float | None = None,
        include_disabled: bool = False,
    ) -> list[ToolMetadata]:
        """Eligible tools for a node — the only ones the LLM should ever see.

        A tool is eligible iff: its phase matches, it is enabled, all its
        ``required_state_flags`` are satisfied, its latency is within budget,
        and its alpha clears ``min_alpha``. Results are ranked highest-alpha
        first (then lowest-latency), so prompt-shrinking keeps the best tools.
        """
        flags = set(available_state_flags or ())
        eligible = [
            t
            for t in self._tools.values()
            if t.phase == phase
            and (include_disabled or t.enabled)
            and set(t.required_state_flags).issubset(flags)
            and (max_latency_ms is None or t.latency_ms <= max_latency_ms)
            and (min_alpha is None or t.alpha_score >= min_alpha)
        ]
        return sorted(eligible, key=lambda t: (-t.alpha_score, t.latency_ms, t.name))

    def capability_graph(self) -> dict[str, list[str]]:
        """name -> tools it unlocks. Powers the operator DAG's tool edges."""
        return {t.name: list(t.unlocks) for t in self._tools.values() if t.unlocks}

    # -- telemetry --
    def record_call(
        self,
        name: str,
        *,
        latency_ms: float,
        success: bool,
        realized_pnl: float | None = None,
    ) -> ToolMetadata | None:
        """Fold one tool invocation into the tool's EMA telemetry.

        ``realized_pnl`` is optional because the buy/sell LLM exercises a tool
        (and learns its latency + reliability) at *decision* time, long before
        the trade's outcome is known. Pass it only from an outcome-aware caller
        (e.g. the grade loop); when omitted, the seeded alpha prior is left
        intact so a stream of zero-PnL decision-time calls can't drag attribution
        to zero.
        """
        tool = self._tools.get(name)
        if tool is None:
            return None
        tool.latency_ms = _ema(tool.latency_ms, latency_ms, count=tool.call_count)
        failure_sample = 0.0 if success else 1.0
        tool.failure_rate = _ema(tool.failure_rate, failure_sample, count=tool.call_count)
        if realized_pnl is not None:
            tool.alpha_score = _ema(tool.alpha_score, realized_pnl, count=tool.call_count)
        tool.call_count += 1
        if success:
            tool.success_count += 1
        return tool

    def disable_dead_tools(
        self,
        *,
        min_calls: int = 20,
        max_failure_rate: float = 0.5,
        min_alpha: float = 0.0,
    ) -> list[str]:
        """Auto-suppress tools that have proven to be noise or unreliable.

        Only tools with enough samples are judged. Returns the names disabled
        so the caller can log/notify. Negative-alpha or high-failure tools are
        suppressed — exactly the ``scan_sector_correlation`` case the directive
        calls out.
        """
        disabled: list[str] = []
        for tool in self._tools.values():
            if not tool.enabled or tool.call_count < min_calls:
                continue
            if tool.failure_rate > max_failure_rate or tool.alpha_score < min_alpha:
                tool.enabled = False
                disabled.append(tool.name)
        return disabled

    def attribution(self) -> list[ToolMetadata]:
        """All tools, ranked by realized alpha — the attribution panel feed."""
        return sorted(self._tools.values(), key=lambda t: (-t.alpha_score, t.name))

    def suggest_tool_changes(
        self,
        *,
        min_calls: int = 20,
        max_failure_rate: float = 0.5,
    ) -> list[ToolSuggestion]:
        """Read-only governance advice: which tools to drop, keep, or review.

        This is the suggestion feed the operator UI renders — the system telling
        a human which tools are pulling weight in the reasoning prompt and which
        are dead weight. It mutates nothing (unlike :meth:`disable_dead_tools`);
        the human stays in the loop. Logic, in priority order per tool:

        * negative alpha            -> disable (drop from the prompt)
        * proven unreliable         -> disable (failure rate high over enough calls)
        * registered but unused     -> review (only once other tools are active)

        Plus a single ``prioritize`` hint for the highest-alpha enabled tool.
        """
        suggestions: list[ToolSuggestion] = []
        total_calls = sum(t.call_count for t in self._tools.values())
        for tool in sorted(self._tools.values(), key=lambda t: (-t.alpha_score, t.name)):
            if not tool.enabled:
                continue
            if tool.alpha_score < 0:
                suggestions.append(
                    ToolSuggestion(
                        tool=tool.name,
                        action="disable",
                        severity="warning",
                        reason=f"negative alpha ({tool.alpha_score:+.2f}) — drop from the prompt",
                    )
                )
            elif tool.call_count >= min_calls and tool.failure_rate > max_failure_rate:
                suggestions.append(
                    ToolSuggestion(
                        tool=tool.name,
                        action="disable",
                        severity="warning",
                        reason=(
                            f"failure rate {tool.failure_rate:.0%} over {tool.call_count} calls"
                        ),
                    )
                )
            elif total_calls > 0 and tool.call_count == 0:
                suggestions.append(
                    ToolSuggestion(
                        tool=tool.name,
                        action="review",
                        severity="info",
                        reason="registered but never exercised by the reasoning node",
                    )
                )

        top = max(
            (t for t in self._tools.values() if t.enabled and t.alpha_score > 0),
            key=lambda t: t.alpha_score,
            default=None,
        )
        if top is not None:
            suggestions.append(
                ToolSuggestion(
                    tool=top.name,
                    action="prioritize",
                    severity="info",
                    reason=f"highest alpha ({top.alpha_score:+.2f}) — keep at the top of the prompt",
                )
            )
        return suggestions


def default_tools() -> list[ToolMetadata]:
    """Seed catalog. Priors are illustrative until live telemetry overwrites them."""
    return [
        ToolMetadata(
            name=TOOL_STREAM_CONFLUENCE,
            phase=ToolPhase.PERCEPTION,
            description="Cross-stream signal confluence for the symbol.",
            alpha_score=0.6,
            latency_ms=42.0,
            unlocks=[TOOL_SECTOR_CORRELATION, TOOL_VWAP_EXECUTION],
        ),
        ToolMetadata(
            name=TOOL_MACRO_REGIME,
            phase=ToolPhase.PERCEPTION,
            description="Current macro regime (risk-on / risk-off / neutral).",
            alpha_score=0.4,
            latency_ms=15.0,
            cache_ttl=300,
        ),
        ToolMetadata(
            name=TOOL_SECTOR_CORRELATION,
            phase=ToolPhase.PERCEPTION,
            description="Sector-correlation scan. Flagged as low/negative alpha.",
            alpha_score=-0.2,
            latency_ms=120.0,
            required_state_flags=[TOOL_FLAG_CONFLUENCE_LOADED],
        ),
        ToolMetadata(
            name=TOOL_ORDER_BOOK_DEPTH,
            phase=ToolPhase.PERCEPTION,
            description="Order-book depth / bid-ask spread for the symbol — gauge "
            "liquidity before sizing.",
            alpha_score=0.35,
            latency_ms=50.0,
        ),
        ToolMetadata(
            name=TOOL_NEWS_SENTIMENT,
            phase=ToolPhase.PERCEPTION,
            description="Recent news sentiment score for the symbol. Cached — news "
            "moves slower than ticks.",
            alpha_score=0.2,
            latency_ms=110.0,
            cache_ttl=300,
        ),
        ToolMetadata(
            name=TOOL_CORRELATION_CHECK,
            phase=ToolPhase.PERCEPTION,
            description="Cross-asset correlation (e.g. BTC vs ETH) so the agent avoids "
            "stacking correlated risk.",
            alpha_score=0.25,
            latency_ms=90.0,
            required_state_flags=[TOOL_FLAG_CONFLUENCE_LOADED],
        ),
        ToolMetadata(
            name=TOOL_QUERY_SIMILAR_TRADES,
            phase=ToolPhase.MEMORY,
            description="Vector-memory recall of similar historical setups.",
            alpha_score=0.5,
            latency_ms=60.0,
        ),
        ToolMetadata(
            name=TOOL_GET_IC_WEIGHTS,
            phase=ToolPhase.MEMORY,
            description="Current factor IC weights from Redis.",
            alpha_score=0.3,
            latency_ms=8.0,
            cache_ttl=90000,
        ),
        ToolMetadata(
            name=TOOL_RISK_CAGE,
            phase=ToolPhase.RISK,
            description="Deterministic risk cage: sizing, exposure, drawdown gates.",
            alpha_score=0.0,
            latency_ms=5.0,
        ),
        ToolMetadata(
            name=TOOL_VWAP_EXECUTION,
            phase=ToolPhase.EXECUTION,
            description="VWAP execution plan to minimize slippage.",
            # Execution mechanics are graded on reliability/latency, not directional
            # alpha — seed neutral so a live VWAP call never shows fake earned edge.
            alpha_score=0.0,
            latency_ms=30.0,
            required_state_flags=[TOOL_FLAG_RISK_APPROVED],
        ),
        ToolMetadata(
            name=TOOL_BRACKET_ORDER,
            phase=ToolPhase.EXECUTION,
            description="Place a bracket order. Gated on risk + committed thesis.",
            alpha_score=0.0,
            latency_ms=200.0,
            required_state_flags=[TOOL_FLAG_RISK_APPROVED, TOOL_FLAG_THESIS_COMMITTED],
        ),
        ToolMetadata(
            name=TOOL_REPLAY_REGRESSION,
            phase=ToolPhase.OPTIMIZATION,
            description="Replay a candidate config against history (challenger only).",
            alpha_score=0.0,
            latency_ms=1500.0,
        ),
    ]


_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Return the process-wide registry, seeding the default catalog on first use."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _registry.register_many(default_tools())
    return _registry


def set_tool_registry(registry: ToolRegistry | None) -> None:
    """Replace the singleton (tests reset to a fresh registry)."""
    global _registry
    _registry = registry
