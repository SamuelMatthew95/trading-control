"""COGNITIVE LOOP — one synchronized brain on one event stream.

Wires every subsystem into the single closed loop and emits a typed event at
every stage, so the whole brain is reconstructable from the stream alone:

    perceive (agents) -> aggregate -> decide -> risk gate -> execute
        -> close_trade (outcome, attribution, grade)
        -> learn (observations) -> evolve (propose -> shadow backtest -> challenge -> PR)
        -> merge (new config version)  ->  perceive ...

Guarantees by construction:
  * The decision step is pure math; agents are advisory and never gate a trade.
  * Learning emits observations only; the Proposal Agent turns them into typed
    candidates; the backtest judges; the challenger validates; only a merge (a
    reviewed PR) changes ``self.config``.  ``evolve`` NEVER mutates the config.
  * :meth:`snapshot` is a pure read of the stream + folds — the UI mirror.
"""

from __future__ import annotations

from typing import Any

from cognitive.agents import MarketView
from cognitive.aggregation import aggregate
from cognitive.backtest_gate import evaluate_proposal, walk_forward
from cognitive.challenger import review as challenger_review
from cognitive.config import CognitiveConfig, load_config
from cognitive.decision import decide
from cognitive.events import EventStream, EventType
from cognitive.execution import execute
from cognitive.gitops import apply_proposal_to_config, build_pull_request
from cognitive.governance import ProposalGovernor
from cognitive.grading import grade_agent, grade_config_version, grade_proposal, grade_trade
from cognitive.health import assess_health
from cognitive.learning import ImportanceTracker, LearningEngine, attribute
from cognitive.proposal import (
    ProposalAgent,
    ProposalQueue,
    ProposalScorecard,
    ProposalStatus,
)
from cognitive.registry import (
    ROLE_PROPOSAL,
    ROLE_REASONING,
    ROLE_SIGNAL,
    AgentRegistry,
    build_default_registry,
)
from cognitive.risk import evaluate_risk
from cognitive.trace import build_trace

SOURCE_AGGREGATOR = "aggregator"
SOURCE_DECISION = "decision_engine"
SOURCE_RISK = "risk_engine"
SOURCE_EXECUTION = "execution_engine"
SOURCE_LEARNING = "learning_engine"
SOURCE_GITOPS = "gitops"
SOURCE_MERGE = "config_merge"


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


class CognitiveLoop:
    """The single synchronized, deterministic, event-stream-driven brain."""

    def __init__(
        self,
        config: CognitiveConfig | None = None,
        *,
        stream: EventStream | None = None,
        registry: AgentRegistry | None = None,
        max_events: int = 100_000,
    ) -> None:
        # Bounded retention so the in-process stream can't grow without limit.
        self.stream = stream or EventStream(max_events=max_events)
        self.config = config or load_config()
        self.registry = registry or build_default_registry()
        self.learning = LearningEngine()
        self.importance = ImportanceTracker()
        self.scorecard = ProposalScorecard()
        self.governor = ProposalGovernor()
        self.queue = ProposalQueue()
        # Provenance of the active config: which merged proposal produced it.
        self._config_proposal_id: str | None = None

        signal_agents = {spec.emits: spec.instance for spec in self.registry.by_role(ROLE_SIGNAL)}
        self.news = signal_agents[EventType.NEWS_SIGNAL.value]
        self.tech = signal_agents[EventType.TECH_SIGNAL.value]
        self.macro = signal_agents[EventType.MACRO_SIGNAL.value]
        self.risk = signal_agents[EventType.RISK_SIGNAL.value]
        self.reasoning = self.registry.by_role(ROLE_REASONING)[0].instance
        self.proposal_agent: ProposalAgent = self.registry.by_role(ROLE_PROPOSAL)[0].instance

        self._emit_config_version(grade=None)

    # ------------------------------------------------------------------ #
    # Forward pass: market -> decision -> execution
    # ------------------------------------------------------------------ #
    def step(
        self,
        market: MarketView,
        *,
        equity: float,
        position_pct: float,
        current_exposure_pct: float = 0.0,
        day_pnl_pct: float = 0.0,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Run one full perceive -> decide -> gate -> execute cycle on the stream."""
        trace_id = trace_id or f"trace-{len(self.stream)}"
        news = self.news.emit(self.stream, market, trace_id=trace_id)
        tech = self.tech.emit(self.stream, market, trace_id=trace_id)
        macro = self.macro.emit(self.stream, market, trace_id=trace_id)
        risk = self.risk.emit(self.stream, market, trace_id=trace_id)

        features = aggregate(news, tech, macro, risk)
        self.stream.emit(
            EventType.FEATURES,
            {"type": EventType.FEATURES.value, **features},
            trace_id=trace_id,
            source=SOURCE_AGGREGATOR,
            ts=market.ts,
        )
        self.reasoning.emit(self.stream, features, trace_id=trace_id, ts=market.ts)

        decision = decide(features, self.config)
        decision_payload = decision.as_dict()
        # Config lineage: every trade records which config version (and the merged
        # proposal that produced it) drove the decision — so "which change caused
        # this drawdown?" is answerable months later.
        decision_payload["config_version"] = self.config.version
        decision_payload["config_proposal_id"] = self._config_proposal_id
        self.stream.emit(
            EventType.DECISION,
            decision_payload,
            trace_id=trace_id,
            source=SOURCE_DECISION,
            ts=market.ts,
        )

        gate = evaluate_risk(
            decision,
            config=self.config,
            requested_position_pct=position_pct,
            current_exposure_pct=current_exposure_pct,
            day_pnl_pct=day_pnl_pct,
        )
        self.stream.emit(
            EventType.RISK_GATE, gate.as_dict(), trace_id=trace_id, source=SOURCE_RISK, ts=market.ts
        )

        execution = execute(decision, gate, symbol=market.symbol, price=market.price, equity=equity)
        execution_payload = execution.as_dict()
        execution_payload["config_version"] = self.config.version
        execution_payload["config_proposal_id"] = self._config_proposal_id
        self.stream.emit(
            EventType.EXECUTION,
            execution_payload,
            trace_id=trace_id,
            source=SOURCE_EXECUTION,
            ts=market.ts,
        )
        return {
            "trace_id": trace_id,
            "features": features,
            "decision": decision,
            "gate": gate,
            "execution": execution,
        }

    def _decision_for(self, trace_id: str) -> dict[str, Any] | None:
        for event in reversed(list(self.stream)):
            if event.kind == EventType.DECISION and event.trace_id == trace_id:
                return event.payload
        return None

    # ------------------------------------------------------------------ #
    # Post-trade: outcome -> attribution -> multi-dimensional grade
    # ------------------------------------------------------------------ #
    def close_trade(
        self,
        trace_id: str,
        *,
        realized_pnl: float,
        realized_pnl_pct: float,
        max_adverse_pct: float,
        slippage_bps: float,
        side: str,
        entry_price: float,
        window_low: float,
        window_high: float,
    ) -> dict[str, Any]:
        """Record a closed trade's outcome, attribute PnL, and grade it."""
        decision_payload = self._decision_for(trace_id) or {}
        breakdown = dict(decision_payload.get("breakdown", {}))
        decision_score = float(decision_payload.get("score", 0.0))

        self.stream.emit(
            EventType.TRADE_OUTCOME,
            {
                "type": EventType.TRADE_OUTCOME.value,
                "realized_pnl": round(realized_pnl, 6),
                "realized_pnl_pct": round(realized_pnl_pct, 6),
                "side": side,
                "config_version": int(decision_payload.get("config_version", self.config.version)),
                "config_proposal_id": decision_payload.get("config_proposal_id"),
            },
            trace_id=trace_id,
            source=SOURCE_EXECUTION,
        )

        attribution = attribute(breakdown, realized_pnl)
        self.stream.emit(
            EventType.ATTRIBUTION, attribution.as_dict(), trace_id=trace_id, source=SOURCE_LEARNING
        )
        self.importance.update(attribution, outcome_sign=_sign(realized_pnl))

        card = grade_trade(
            trade_id=trace_id,
            decision_score=decision_score,
            realized_pnl_pct=realized_pnl_pct,
            max_adverse_pct=max_adverse_pct,
            slippage_bps=slippage_bps,
            side=side,
            entry_price=entry_price,
            window_low=window_low,
            window_high=window_high,
        )
        self.stream.emit(EventType.GRADE, card.as_dict(), trace_id=trace_id, source=SOURCE_LEARNING)
        return {"attribution": attribution, "grade": card}

    # ------------------------------------------------------------------ #
    # Learning: observations + rolling agent grades (edits nothing)
    # ------------------------------------------------------------------ #
    def learn(self) -> list[Any]:
        """Emit observations and rolling agent grades; change nothing."""
        metadata = self.importance.metadata()
        observations = self.learning.observe(metadata)
        for observation in observations:
            self.stream.emit(EventType.OBSERVATION, observation.as_dict(), source=SOURCE_LEARNING)
        for signal, stats in metadata.items():
            self.stream.emit(
                EventType.GRADE, grade_agent(signal, stats).as_dict(), source=SOURCE_LEARNING
            )
        return observations

    def _attribution_supports(self, signal: str, direction: int) -> bool:
        stats = self.importance.metadata().get(signal, {})
        good = (
            stats.get("total_pnl_attribution", 0.0) >= 0 and stats.get("correct_rate", 0.0) >= 0.5
        )
        return good if direction > 0 else not good

    # ------------------------------------------------------------------ #
    # Evolution: propose -> shadow backtest -> challenge -> PR (NO merge)
    # ------------------------------------------------------------------ #
    def evolve(
        self,
        prices: list[float],
        *,
        split: float = 0.5,
        slippage_seed: int = 0,
        base_ref: str = "main",
        news: list[float] | None = None,
        folds: int = 4,
    ) -> dict[str, Any] | None:
        """Run one evolution cycle. Returns the evidence bundle, or None if no proposal.

        It NEVER mutates ``self.config`` — an approved proposal yields a PR plan;
        only :meth:`merge` (a reviewed PR landing) changes behaviour.
        """
        observations = self.learn()
        proposal = self.proposal_agent.propose(observations, self.config, self.scorecard)
        if proposal is None:
            return None

        self.proposal_agent.emit(self.stream, proposal)

        # Governance: quota / dedup / cooldown — refuse noisy or repeat proposals
        # BEFORE spending a backtest on them.
        admitted, reason = self.governor.admit(proposal)
        if not admitted:
            self.queue.add(proposal, status=ProposalStatus.BLOCKED.value)
            self.queue.update(proposal.proposal_id, verdict={"blocked": reason})
            return {"proposal": proposal, "blocked": reason}

        self.queue.add(proposal, status=ProposalStatus.BACKTESTING.value)

        candidate = apply_proposal_to_config(self.config, proposal)
        if candidate is None:
            self.governor.record_outcome(proposal, approved=False)
            self.queue.update(proposal.proposal_id, status=ProposalStatus.REJECTED.value)
            return {"proposal": proposal, "rejected": "proposal does not map to a valid config"}

        cut = max(1, int(len(prices) * split))
        in_prices, out_prices = prices[:cut], prices[cut:]
        in_news = None if news is None else news[:cut]
        out_news = None if news is None else news[cut:]
        in_delta = evaluate_proposal(
            in_prices, self.config, candidate, news=in_news, slippage_seed=slippage_seed
        )
        out_delta = evaluate_proposal(
            out_prices, self.config, candidate, news=out_news, slippage_seed=slippage_seed
        )
        # Walk-forward across several market periods — the anti-overfit gate.
        wf = walk_forward(
            prices, self.config, candidate, folds=folds, news=news, slippage_seed=slippage_seed
        )
        self.stream.emit(
            EventType.BACKTEST_RESULT,
            {
                "type": EventType.BACKTEST_RESULT.value,
                "proposal_id": proposal.proposal_id,
                "in_sample": in_delta.as_dict(),
                "out_sample": out_delta.as_dict(),
                "walk_forward": wf.as_dict(),
            },
            source=SOURCE_GITOPS,
        )

        signal = proposal.target.split(".")[-1]
        direction = _sign(float(proposal.new_value) - float(proposal.old_value))
        learning_samples = int(self.importance.metadata().get(signal, {}).get("samples", 0))
        verdict = challenger_review(
            in_sample=in_delta,
            out_sample=out_delta,
            learning_samples=learning_samples,
            candidate_config_valid=True,
            attribution_supports=self._attribution_supports(signal, direction),
            walk_forward_consistency=wf.consistency,
        )
        self.stream.emit(
            EventType.CHALLENGER_VERDICT,
            {**verdict.as_dict(), "proposal_id": proposal.proposal_id},
            source=SOURCE_GITOPS,
        )

        proposal_card = grade_proposal(
            proposal_id=proposal.proposal_id,
            proposal_type=proposal.proposal_type,
            pnl_delta=out_delta.pnl_delta,
            sharpe_delta=out_delta.sharpe_delta,
        )
        self.stream.emit(EventType.GRADE, proposal_card.as_dict(), source=SOURCE_GITOPS)
        self.scorecard.record(proposal.proposal_type, success=verdict.approved)
        self.governor.record_outcome(proposal, approved=verdict.approved)

        bundle: dict[str, Any] = {
            "proposal": proposal,
            "in_sample": in_delta,
            "out_sample": out_delta,
            "walk_forward": wf,
            "verdict": verdict,
            "proposal_grade": proposal_card,
            "candidate_config": candidate,
        }
        if verdict.approved:
            pull_request = build_pull_request(
                proposal, verdict, in_delta, out_delta, self.config, candidate, base_ref=base_ref
            )
            self.stream.emit(EventType.PR_REQUEST, pull_request.as_dict(), source=SOURCE_GITOPS)
            self.queue.update(
                proposal.proposal_id,
                status=ProposalStatus.APPROVED.value,
                verdict=verdict.as_dict(),
                delta=out_delta.as_dict(),
                pull_request=pull_request.as_dict(),
                proposal_grade=proposal_card.as_dict(),
            )
            bundle["pull_request"] = pull_request
        else:
            self.queue.update(
                proposal.proposal_id,
                status=ProposalStatus.REJECTED.value,
                verdict=verdict.as_dict(),
                delta=out_delta.as_dict(),
                proposal_grade=proposal_card.as_dict(),
            )
        return bundle

    def merge(
        self,
        candidate: CognitiveConfig,
        *,
        sharpe: float = 0.0,
        max_drawdown_pct: float = 0.0,
        proposal_id: str | None = None,
    ) -> dict[str, Any]:
        """Simulate a reviewed PR landing: adopt the config + record a version grade."""
        self.config = candidate
        self._config_proposal_id = proposal_id  # provenance for trades on this config
        if proposal_id is not None:
            self.queue.update(proposal_id, status=ProposalStatus.MERGED.value)
        grade = grade_config_version(
            version=candidate.version, sharpe=sharpe, max_drawdown_pct=max_drawdown_pct
        )
        self._emit_config_version(grade=grade)
        return {"version": candidate.version, "grade": grade}

    def _emit_config_version(self, *, grade: Any) -> None:
        self.stream.emit(
            EventType.CONFIG_VERSION,
            {
                "type": EventType.CONFIG_VERSION.value,
                "version": self.config.version,
                "config": self.config.to_dict(),
                "grade": grade.as_dict() if grade is not None else None,
            },
            source=SOURCE_MERGE,
        )

    # ------------------------------------------------------------------ #
    # Read-only mirror: the 7-tab UI snapshot
    # ------------------------------------------------------------------ #
    def _payloads(self, kind: EventType, *, limit: int | None = None) -> list[dict[str, Any]]:
        out = [
            {**event.payload, "seq": event.seq, "trace_id": event.trace_id, "source": event.source}
            for event in self.stream.events(kind=kind)
        ]
        return out[-limit:] if limit is not None else out

    def _trace_ids(self, limit: int) -> list[str]:
        seen: list[str] = []
        for event in self.stream:
            if event.kind == EventType.DECISION and event.trace_id and event.trace_id not in seen:
                seen.append(event.trace_id)
        return seen[-limit:]

    def snapshot(self, *, trace_limit: int = 20) -> dict[str, Any]:
        """The read-only mirror that backs the observability UI (7 tabs + health)."""
        metadata = self.importance.metadata()
        agent_grades = [grade_agent(signal, stats).as_dict() for signal, stats in metadata.items()]
        config_versions = self._payloads(EventType.CONFIG_VERSION)
        latest_decision = self._payloads(EventType.DECISION, limit=1)
        return {
            "config": self.config.to_dict(),
            "agents_roster": self.registry.describe(),
            "live_agents": {
                "news": (self._payloads(EventType.NEWS_SIGNAL, limit=1) or [None])[-1],
                "tech": (self._payloads(EventType.TECH_SIGNAL, limit=1) or [None])[-1],
                "macro": (self._payloads(EventType.MACRO_SIGNAL, limit=1) or [None])[-1],
                "risk": (self._payloads(EventType.RISK_SIGNAL, limit=1) or [None])[-1],
            },
            "reasoning": self._payloads(EventType.REASONING, limit=trace_limit),
            "decision": {
                "latest": latest_decision[-1] if latest_decision else None,
                "recent": self._payloads(EventType.DECISION, limit=trace_limit),
                "weights": self.config.weights,
                "buy_threshold": self.config.buy_threshold,
                "sell_threshold": self.config.sell_threshold,
            },
            "proposals": self.queue.snapshot(),
            "challenger": self._payloads(EventType.CHALLENGER_VERDICT, limit=trace_limit),
            "learning": {
                "importance": metadata,
                "agent_grades": agent_grades,
                "observations": self._payloads(EventType.OBSERVATION, limit=trace_limit),
                "trade_grades": [
                    payload
                    for payload in self._payloads(EventType.GRADE)
                    if payload.get("subject") == "trade"
                ][-trace_limit:],
            },
            "evolution": {
                "config_versions": config_versions,
                "proposal_success_rates": self.scorecard.snapshot(),
                "agent_grades": agent_grades,
                "governor": self.governor.snapshot(),
            },
            "health": assess_health(self.stream),
            "traces": [
                build_trace(self.stream, trace_id) for trace_id in self._trace_ids(trace_limit)
            ],
            "event_count": len(self.stream),
        }
