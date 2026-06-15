"""Modular production-oriented multi-agent trading orchestrator."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.constants import FieldName
from api.services.multi_agent_memory import (
    ConversationMemory,
    PersistentMemory,
    TaskStateMemory,
)
from api.services.multi_agent_models import AgentCall, PlanStep
from api.services.multi_agent_pipeline import EvaluationLayer, ExecutionEngine, Planner
from api.services.multi_agent_reasoning import (
    AnthropicReasoningModel,
    DeterministicReasoningModel,
    ReasoningModel,
)
from api.services.multi_agent_tools import DocumentRetriever, TradeTools

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class MultiAgentOrchestrator:
    """Production-grade orchestrator with planner/executor/memory/eval layers."""

    def __init__(self, api_key: str | None = None):
        model: ReasoningModel
        if api_key:
            model = AnthropicReasoningModel(api_key)
        else:
            model = DeterministicReasoningModel()
        self.planner = Planner()
        self.executor = ExecutionEngine(model, DocumentRetriever(), TradeTools())
        self.conversation_memory = ConversationMemory(limit=20)
        self.task_memory = TaskStateMemory()
        self.persistent_memory = PersistentMemory()
        self.evaluator = EvaluationLayer()
        self.agent_calls: list[AgentCall] = []
        self.trade_log: list[dict[str, Any]] = []

    def analyze_trade(
        self,
        asset: str,
        timeframe: str,
        portfolio_state: dict[str, Any],
        *,
        max_iterations: int = 2,
    ) -> dict[str, Any]:
        """Run an explicit agentic loop: perceive → think/plan → act → evaluate → repeat."""
        self.agent_calls = []
        current_timeframe = timeframe
        final_decision: dict[str, Any] | None = None
        final_trajectory_issues: list[str] = []
        final_outcome_issues: list[str] = []

        for iteration in range(1, max_iterations + 1):
            decision, trajectory_issues, outcome_issues = self._analyze_trade_once(
                asset, current_timeframe, portfolio_state
            )
            decision["LOOP_ITERATION"] = iteration
            final_decision = decision
            final_trajectory_issues = trajectory_issues
            final_outcome_issues = outcome_issues
            if not self._should_retry(
                decision, trajectory_issues, outcome_issues, iteration, max_iterations
            ):
                break
            current_timeframe = self._next_timeframe(current_timeframe)
            self.conversation_memory.add(
                {
                    FieldName.LOOP_EVENT: "retry",
                    FieldName.ITERATION: iteration,
                    FieldName.NEXT_TIMEFRAME: current_timeframe,
                    FieldName.REASON: "low_confidence_or_validation_issues",
                }
            )

        if final_decision is None:
            return self._error_decision(asset, "orchestrator produced no decision")

        if final_trajectory_issues or final_outcome_issues:
            final_decision.setdefault("RISK FLAGS", []).extend(
                final_trajectory_issues + final_outcome_issues
            )
        final_decision["LOOP_COMPLETED"] = True
        final_decision["LOOP_MAX_ITERATIONS"] = max_iterations
        return final_decision

    def _analyze_trade_once(
        self, asset: str, timeframe: str, portfolio_state: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        task_id = f"{asset}:{datetime.now(timezone.utc).isoformat()}"
        plan = self.planner.build_plan(asset, timeframe)
        context: dict[str, Any] = {
            FieldName.ASSET: asset,
            FieldName.TIMEFRAME: timeframe,
            FieldName.PORTFOLIO_STATE: portfolio_state,
        }

        for step in plan.steps:
            step_start = time.time()
            try:
                if step.name == "signal":
                    context[FieldName.SIGNALS] = self.executor.run_step(step, context)
                elif step.name == "consensus":
                    context[FieldName.CONSENSUS] = self.executor.run_step(step, context)
                    if (
                        float(context[FieldName.CONSENSUS].get(FieldName.AGREEMENT_RATIO, 0.0))
                        < 0.5
                    ):
                        context[FieldName.RISK] = {
                            FieldName.VETO: True,
                            FieldName.FLAGS: ["LOW_CONSENSUS"],
                        }
                        context[FieldName.SIZING] = {
                            FieldName.UNITS: 0,
                            FieldName.ENTRY: 0,
                            FieldName.STOP: 0,
                            FieldName.TARGET: 0,
                            FieldName.RR_RATIO: 0,
                        }
                        break
                elif step.name == "risk":
                    context[FieldName.RISK] = self.executor.run_step(step, context)
                    if bool(context[FieldName.RISK].get(FieldName.VETO, False)):
                        context[FieldName.SIZING] = {
                            FieldName.UNITS: 0,
                            FieldName.ENTRY: 0,
                            FieldName.STOP: 0,
                            FieldName.TARGET: 0,
                            FieldName.RR_RATIO: 0,
                        }
                        break
                elif step.name == "sizing":
                    context[FieldName.SIZING] = self.executor.run_step(step, context)
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                agent_name = (
                    "skipped_by_memory_guard"
                    if FieldName.SKIPPED_BY_MEMORY_GUARD in error_text
                    else step.name.upper()
                )
                self.agent_calls.append(
                    AgentCall(
                        agent_name,
                        context.copy(),
                        {},
                        datetime.now(timezone.utc),
                        False,
                        error=error_text,
                        duration_ms=int((time.time() - step_start) * 1000),
                    )
                )
                decision = self._error_decision(asset, error_text)
                decision[FieldName.CONTEXT_DUMP] = {
                    FieldName.TASK_STATE: self.task_memory.get(task_id),
                    FieldName.RETRIEVED_CONTEXT: context.get(FieldName.SIGNALS, []),
                }
                self._persist(task_id, decision)
                return decision, ["step_failure"], []

            self.agent_calls.append(
                AgentCall(
                    step.name.upper(),
                    context.copy(),
                    context.get(step.name, {}),
                    datetime.now(timezone.utc),
                    True,
                    duration_ms=int((time.time() - step_start) * 1000),
                )
            )
            self.task_memory.put(
                task_id, {FieldName.LAST_STEP: step.name, FieldName.CONTEXT: context.copy()}
            )

        decision = self.executor.run_step(PlanStep("decision"), context)
        trajectory_issues = self.evaluator.validate_trajectory(self.agent_calls)
        outcome_issues = self.evaluator.validate_outcome(decision)
        self._persist(task_id, decision)
        return decision, trajectory_issues, outcome_issues

    def _should_retry(
        self,
        decision: dict[str, Any],
        trajectory_issues: list[str],
        outcome_issues: list[str],
        iteration: int,
        max_iterations: int,
    ) -> bool:
        if iteration >= max_iterations:
            return False
        if "SYSTEM_ERROR" in decision.get("RISK FLAGS", []):
            return False
        if trajectory_issues or outcome_issues:
            return True
        if decision.get("CONFIDENCE") == "LOW":
            return True
        return "LOW_CONSENSUS" in decision.get("RISK FLAGS", [])

    def _next_timeframe(self, timeframe: str) -> str:
        fallback_order = {"1W": "1D", "1D": "4H", "4H": "1H", "1H": "1D"}
        return fallback_order.get(timeframe, "1D")

    def process_trade_signals(self, signals: list[dict[str, Any]]) -> dict[str, Any]:
        symbol = signals[0].get(FieldName.SYMBOL, "AAPL") if signals else "AAPL"
        price = float(signals[0].get(FieldName.PRICE, 100)) if signals else 100
        portfolio = {
            FieldName.TOTAL_VALUE: 100000,
            FieldName.CASH: 50000,
            FieldName.POSITIONS: {},
            FieldName.DRAWDOWN: -0.03,
            FieldName.PRICE_HINT: price,
        }
        decision = self.analyze_trade(symbol, "1D", portfolio)
        return {
            "DECISION": decision["DECISION"],
            FieldName.CONFIDENCE: 0.8 if decision["CONFIDENCE"] == "HIGH" else 0.6,
            FieldName.REASONING: decision["RATIONALE"],
            FieldName.POSITION_SIZE: 0.02,
            FieldName.RISK_ASSESSMENT: {FieldName.FLAGS: decision.get("RISK FLAGS", [])},
        }

    def _error_decision(self, asset: str, message: str) -> dict[str, Any]:
        return {
            "DECISION": "FLAT",
            "ASSET": asset,
            "SIZE": "0 units",
            "ENTRY": "0.00",
            "STOP": "0.00",
            "TARGET": "0.00",
            "R/R RATIO": "0.0:1",
            "CONFIDENCE": "LOW",
            "SIGNAL SUMMARY": [f"error={message}"],
            "RISK FLAGS": ["SYSTEM_ERROR"],
            "RATIONALE": "Execution failed",
            "INVALIDATION": "N/A",
        }

    def _persist(self, task_id: str, decision: dict[str, Any]) -> None:
        log_entry = {
            FieldName.TRACE_SUMMARY: {FieldName.GUARD_HITS: self.executor.tools.guard_hits},
            FieldName.TASK_ID: task_id,
            FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            FieldName.DECISION: decision,
            FieldName.TRACE: [asdict(call) for call in self.agent_calls],
        }
        self.conversation_memory.add(log_entry)
        self.trade_log.append(log_entry)
        self.persistent_memory.append_trade(log_entry)
        Path("trade-log.json").write_text(
            json.dumps(self.trade_log, indent=2, default=str), encoding="utf-8"
        )
