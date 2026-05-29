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

from api.constants import ToolPhase

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
        realized_pnl: float = 0.0,
    ) -> ToolMetadata | None:
        """Fold one tool invocation into the tool's EMA telemetry."""
        tool = self._tools.get(name)
        if tool is None:
            return None
        tool.latency_ms = _ema(tool.latency_ms, latency_ms, count=tool.call_count)
        failure_sample = 0.0 if success else 1.0
        tool.failure_rate = _ema(tool.failure_rate, failure_sample, count=tool.call_count)
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


def default_tools() -> list[ToolMetadata]:
    """Seed catalog. Priors are illustrative until live telemetry overwrites them."""
    return [
        ToolMetadata(
            name="get_stream_confluence_metrics",
            phase=ToolPhase.PERCEPTION,
            description="Cross-stream signal confluence for the symbol.",
            alpha_score=0.6,
            latency_ms=42.0,
            unlocks=["scan_sector_correlation", "calculate_vwap_execution"],
        ),
        ToolMetadata(
            name="fetch_macro_regime",
            phase=ToolPhase.PERCEPTION,
            description="Current macro regime (risk-on / risk-off / neutral).",
            alpha_score=0.4,
            latency_ms=15.0,
            cache_ttl=300,
        ),
        ToolMetadata(
            name="scan_sector_correlation",
            phase=ToolPhase.PERCEPTION,
            description="Sector-correlation scan. Flagged as low/negative alpha.",
            alpha_score=-0.2,
            latency_ms=120.0,
            required_state_flags=["confluence_loaded"],
        ),
        ToolMetadata(
            name="query_similar_trades",
            phase=ToolPhase.MEMORY,
            description="Vector-memory recall of similar historical setups.",
            alpha_score=0.5,
            latency_ms=60.0,
        ),
        ToolMetadata(
            name="get_ic_weights",
            phase=ToolPhase.MEMORY,
            description="Current factor IC weights from Redis.",
            alpha_score=0.3,
            latency_ms=8.0,
            cache_ttl=90000,
        ),
        ToolMetadata(
            name="evaluate_risk_cage",
            phase=ToolPhase.RISK,
            description="Deterministic risk cage: sizing, exposure, drawdown gates.",
            alpha_score=0.0,
            latency_ms=5.0,
        ),
        ToolMetadata(
            name="calculate_vwap_execution",
            phase=ToolPhase.EXECUTION,
            description="VWAP execution plan to minimize slippage.",
            alpha_score=0.8,
            latency_ms=30.0,
            required_state_flags=["risk_approved"],
        ),
        ToolMetadata(
            name="execute_bracket_order",
            phase=ToolPhase.EXECUTION,
            description="Place a bracket order. Gated on risk + committed thesis.",
            alpha_score=0.0,
            latency_ms=200.0,
            required_state_flags=["risk_approved", "thesis_committed"],
        ),
        ToolMetadata(
            name="replay_regression_check",
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
