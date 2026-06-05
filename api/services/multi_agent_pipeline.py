"""Planning, execution, and evaluation layers for the multi-agent orchestrator."""

from __future__ import annotations

from typing import Any

from api.constants import FieldName
from api.services.agents.prompts import ADAPTIVE_TRADING_SYSTEM_PROMPT
from api.services.multi_agent_models import AgentCall, PlanStep, TradePlan
from api.services.multi_agent_reasoning import ReasoningModel
from api.services.multi_agent_tools import DocumentRetriever, TradeTools


class Planner:
    def build_plan(self, asset: str, timeframe: str) -> TradePlan:
        return TradePlan(
            asset=asset,
            timeframe=timeframe,
            steps=[
                PlanStep("signal"),
                PlanStep("consensus"),
                PlanStep("risk"),
                PlanStep("sizing"),
                PlanStep("decision"),
            ],
        )


class ExecutionEngine:
    AGENT_PROMPTS: dict[str, str] = {
        "SIGNAL_AGENT": ADAPTIVE_TRADING_SYSTEM_PROMPT,
        "CONSENSUS_AGENT": "You aggregate signals with IC-weighted consensus. Return JSON object only.",
        "RISK_AGENT": "You enforce capital preservation first and can veto trades. Return JSON object only.",
        "SIZING_AGENT": "You calculate Kelly-based position sizing with risk multipliers. Return JSON object only.",
    }

    def __init__(self, model: ReasoningModel, retriever: DocumentRetriever, tools: TradeTools):
        self.model = model
        self.retriever = retriever
        self.tools = tools

    def run_step(self, step: PlanStep, context: dict[str, Any]) -> dict[str, Any]:
        if step.name == "signal":
            grounding = self.retriever.retrieve(
                f"{context[FieldName.ASSET]} {context[FieldName.TIMEFRAME]} signal"
            )
            payload = {
                FieldName.ASSET: context[FieldName.ASSET],
                FieldName.TIMEFRAME: context[FieldName.TIMEFRAME],
                FieldName.GROUNDING: grounding,
            }
            return self.model.complete_json(
                system_prompt=self.AGENT_PROMPTS["SIGNAL_AGENT"], payload=payload
            )
        if step.name == "consensus":
            return self.model.complete_json(
                system_prompt=self.AGENT_PROMPTS["CONSENSUS_AGENT"],
                payload={FieldName.SIGNALS: context[FieldName.SIGNALS]},
            )
        if step.name == "risk":
            return self.model.complete_json(
                system_prompt=self.AGENT_PROMPTS["RISK_AGENT"],
                payload={
                    FieldName.CONSENSUS: context[FieldName.CONSENSUS],
                    FieldName.PORTFOLIO: context[FieldName.PORTFOLIO_STATE],
                },
            )
        if step.name == "sizing":
            return self.model.complete_json(
                system_prompt=self.AGENT_PROMPTS["SIZING_AGENT"],
                payload={
                    FieldName.CONSENSUS: context[FieldName.CONSENSUS],
                    FieldName.RISK: context[FieldName.RISK],
                    FieldName.ASSET_PRICE: self.tools.get_current_price(context[FieldName.ASSET]),
                    FieldName.ATR: self.tools.get_atr(
                        context[FieldName.ASSET], context[FieldName.TIMEFRAME]
                    ),
                    FieldName.PORTFOLIO_VALUE: context[FieldName.PORTFOLIO_STATE].get(
                        FieldName.TOTAL_VALUE, 100000
                    ),
                },
            )
        if step.name == "decision":
            return self._format_decision(context)
        raise ValueError(f"Unknown plan step {step.name}")

    def _format_decision(self, context: dict[str, Any]) -> dict[str, Any]:
        consensus = context[FieldName.CONSENSUS]
        risk = context[FieldName.RISK]
        sizing = context[FieldName.SIZING]
        signal_strength = float(consensus.get(FieldName.SIGNAL_STRENGTH, 0))
        confidence = (
            "HIGH" if signal_strength > 0.8 else "MEDIUM" if signal_strength > 0.6 else "LOW"
        )
        return {
            "DECISION": consensus.get(FieldName.DIRECTION, "FLAT"),
            "ASSET": context[FieldName.ASSET],
            "SIZE": f"{sizing.get(FieldName.UNITS, 0)} units",
            "ENTRY": f"{float(sizing.get(FieldName.ENTRY, 0)):.2f}",
            "STOP": f"{float(sizing.get(FieldName.STOP, 0)):.2f}",
            "TARGET": f"{float(sizing.get(FieldName.TARGET, 0)):.2f}",
            "R/R RATIO": f"{float(sizing.get(FieldName.RR_RATIO, 0)):.1f}:1",
            "CONFIDENCE": confidence,
            "SIGNAL SUMMARY": [
                f"Consensus={consensus.get(FieldName.AGREEMENT_RATIO, 0):.1%}",
                f"Risk veto={risk.get(FieldName.VETO, False)}",
            ],
            "RISK FLAGS": risk.get(FieldName.FLAGS, []),
            "RATIONALE": "Grounded decision via planner/executor pipeline.",
            "INVALIDATION": f"Below stop {float(sizing.get(FieldName.STOP, 0)):.2f}",
            "TRACE SUMMARY": {FieldName.GUARD_HITS: self.tools.guard_hits},
        }


class EvaluationLayer:
    def validate_trajectory(self, trace: list[AgentCall]) -> list[str]:
        issues = []
        if not trace:
            issues.append("empty_trace")
        if any(not call.success for call in trace):
            issues.append("step_failure")
        return issues

    def validate_outcome(self, decision: dict[str, Any]) -> list[str]:
        required = {"DECISION", "ASSET", "SIZE", "CONFIDENCE"}
        missing = sorted(required - set(decision))
        return [f"missing:{k}" for k in missing]
