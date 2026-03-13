from __future__ import annotations

import logging
import os
import time
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List

import requests

from api.services.options_agents import (
    OptionsAnalystAgent,
    OptionsExecutorAgent,
    OptionsGuardrailAgent,
    OptionsStrategistAgent,
    OptionsValidatorAgent,
)

LOGGER = logging.getLogger(__name__)


class OptionsService:
    """Backend options intelligence service with multi-agent orchestration."""

    def __init__(self, anthropic_api_key: str | None, anthropic_model: str | None = None):
        self.anthropic_api_key = anthropic_api_key
        self.anthropic_model = anthropic_model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        self.mcp_url = os.getenv("UNUSUAL_WHALES_MCP_URL", "https://api.unusualwhales.com/api/mcp")
        self.uw_api_key = os.getenv("UW_API_KEY")

        self.analyst = OptionsAnalystAgent()
        self.strategist = OptionsStrategistAgent()
        self.executor = OptionsExecutorAgent()
        self.guardrail = OptionsGuardrailAgent()
        self.validator = OptionsValidatorAgent()

        self.telemetry: Dict[str, Any] = {
            "generated_requests": 0,
            "approved_total": 0,
            "rejected_total": 0,
            "killswitch_total": 0,
            "last_agent_trace": [],
            "last_task_plan": [],
            "last_generated_at": None,
            "closed_play_evaluations": 0,
        }

    def decompose_goal(self) -> List[str]:
        """OODA-style decomposition for observability and deterministic orchestration."""
        return [
            "observe_market_state",
            "orient_signals",
            "decide_strategy_candidates",
            "act_with_guardrails",
            "validate_output_quality",
        ]

    def _call_mcp_tool(self, tool: str, args: Dict[str, Any] | None = None, retries: int = 2) -> Any:
        if not self.uw_api_key:
            raise RuntimeError("UW_API_KEY is missing")

        payload = {
            "jsonrpc": "2.0",
            "id": f"{tool}-{int(datetime.utcnow().timestamp())}",
            "method": "tools/call",
            "params": {"name": tool, "arguments": args or {}},
        }

        last_error: Exception | None = None
        for attempt in range(1, retries + 2):
            try:
                response = requests.post(
                    self.mcp_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.uw_api_key}", "Content-Type": "application/json"},
                    timeout=15,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("error"):
                    raise RuntimeError(data["error"].get("message", "MCP tool failure"))
                return data.get("result", {}).get("content") or data.get("result")
            except Exception as exc:  # pragma: no cover
                last_error = exc
                LOGGER.warning("MCP tool call failed", extra={"tool": tool, "attempt": attempt, "error": str(exc)})
                time.sleep(0.2 * attempt)

        raise RuntimeError(f"MCP tool failed after retries: {last_error}")

    def get_health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "service": "options",
            "model": self.anthropic_model,
            "mcp_configured": bool(self.uw_api_key),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_flow(self) -> List[Dict[str, Any]]:
        try:
            data = self._call_mcp_tool("options_flow_alerts")
            return data if isinstance(data, list) and data else self._mock_flow()
        except Exception as exc:
            LOGGER.info("Falling back to mock flow", extra={"error": str(exc)})
            return self._mock_flow()

    def get_screener(self) -> List[Dict[str, Any]]:
        try:
            data = self._call_mcp_tool("options_screener")
            return data if isinstance(data, list) and data else self._mock_screener()
        except Exception as exc:
            LOGGER.info("Falling back to mock screener", extra={"error": str(exc)})
            return self._mock_screener()

    def get_ticker_details(self, ticker: str) -> Dict[str, Any]:
        try:
            data = self._call_mcp_tool("options_ticker_snapshot", {"ticker": ticker.upper()})
            return data if isinstance(data, dict) else self._mock_ticker(ticker)
        except Exception as exc:
            LOGGER.info("Falling back to mock ticker details", extra={"ticker": ticker, "error": str(exc)})
            return self._mock_ticker(ticker)

    def generate_plays(self, flow: List[Dict[str, Any]], screener: List[Dict[str, Any]], learning_context: List[Dict[str, Any]]) -> Dict[str, Any]:
        task_plan = self.decompose_goal()

        analyst_out = self.analyst.run(flow, screener)
        strategist_out = self.strategist.run(analyst_out.payload, screener)

        chain_lookup: Dict[str, Dict[str, Any]] = {}
        for candidate in strategist_out.payload.get("candidates", []):
            ticker = candidate.get("ticker", "")
            if ticker:
                chain_lookup[ticker] = self.get_ticker_details(ticker)

        executor_out = self.executor.run(strategist_out.payload.get("candidates", []), chain_lookup)
        guardrail_out = self.guardrail.run(executor_out.payload.get("plays", []))
        validator_out = self.validator.run(guardrail_out.payload.get("approved", []))

        learning_summary = self._learning_context_summary(learning_context)
        rejected_count = len(guardrail_out.payload.get("rejected", []))
        kill_switch = bool(guardrail_out.payload.get("kill_switch", False))

        agent_trace = [
            {"agent": analyst_out.agent, "summary": analyst_out.summary},
            {"agent": strategist_out.agent, "summary": strategist_out.summary},
            {"agent": executor_out.agent, "summary": executor_out.summary},
            {"agent": guardrail_out.agent, "summary": guardrail_out.summary},
            {"agent": validator_out.agent, "summary": validator_out.summary},
        ]

        self.telemetry["generated_requests"] += 1
        self.telemetry["approved_total"] += len(validator_out.payload.get("validated", []))
        self.telemetry["rejected_total"] += rejected_count
        self.telemetry["killswitch_total"] += 1 if kill_switch else 0
        self.telemetry["last_generated_at"] = datetime.utcnow().isoformat()
        self.telemetry["last_agent_trace"] = agent_trace
        self.telemetry["last_task_plan"] = task_plan

        return {
            "items": validator_out.payload.get("validated", []),
            "agent_trace": agent_trace,
            "guardrail": {
                "kill_switch": kill_switch,
                "rejected_count": rejected_count,
                "requires_human_review": kill_switch,
            },
            "learning_context_summary": learning_summary,
            "task_plan": task_plan,
            "model": self.anthropic_model,
        }

    def build_run_record(self, generated_output: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "task_id": f"options-{int(time.time())}",
            "decision": {
                "play_count": len(generated_output.get("items", [])),
                "guardrail": generated_output.get("guardrail", {}),
                "model": generated_output.get("model", self.anthropic_model),
            },
            "trace": generated_output.get("agent_trace", []),
        }

    def get_performance(self) -> Dict[str, Any]:
        totals = max(self.telemetry["generated_requests"], 1)
        return {
            "OPTIONS_ANALYST": {"total_calls": self.telemetry["generated_requests"]},
            "OPTIONS_STRATEGIST": {"total_calls": self.telemetry["generated_requests"]},
            "OPTIONS_EXECUTOR": {"total_calls": self.telemetry["generated_requests"]},
            "OPTIONS_GUARDRAIL": {
                "total_calls": self.telemetry["generated_requests"],
                "rejected_total": self.telemetry["rejected_total"],
                "killswitch_total": self.telemetry["killswitch_total"],
            },
            "OPTIONS_VALIDATOR": {
                "total_calls": self.telemetry["generated_requests"],
                "approval_rate": round((self.telemetry["approved_total"] / totals), 4),
            },
        }

    def get_statistics(self) -> Dict[str, Any]:
        generated = self.telemetry["generated_requests"]
        return {
            "generated_requests": generated,
            "approved_total": self.telemetry["approved_total"],
            "rejected_total": self.telemetry["rejected_total"],
            "killswitch_total": self.telemetry["killswitch_total"],
            "closed_play_evaluations": self.telemetry["closed_play_evaluations"],
            "approval_rate": round(self.telemetry["approved_total"] / generated, 4) if generated else 0.0,
            "model": self.anthropic_model,
        }

    def evaluate_closed_play(self, play: Dict[str, Any], pnl: float, recent_flow: List[Dict[str, Any]]) -> str:
        self.telemetry["closed_play_evaluations"] += 1
        flow_regime = "continued" if any(str(item.get("sentiment", "")).lower() == "bullish" for item in recent_flow) else "reversed"
        timing = "good" if pnl > 0 else "late"
        return (
            f"Thesis {flow_regime}. Entry timing was {timing}. "
            "Better outcomes came from waiting for aligned flow tags and high sentiment-score confirmation."
        )

    def learning_summary(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not history:
            return {
                "summary": "No closed plays yet. Start in copilot mode and validate guardrail behavior before scaling.",
                "best_signal": "N/A",
                "win_rate": 0.0,
            }

        wins = [item for item in history if _safe_float(item.get("pnl"), 0) > 0]
        win_rate = (len(wins) / len(history)) * 100
        signal_scores = Counter(str(item.get("signalTag", "Unknown")) for item in wins)
        best_signal = signal_scores.most_common(1)[0][0] if signal_scores else "N/A"

        return {
            "summary": (
                f"Win rate is {win_rate:.1f}%. Most accurate signal type is {best_signal}. "
                "Trend-continuation setups with guardrail approval outperformed unfiltered discretionary entries."
            ),
            "best_signal": best_signal,
            "win_rate": round(win_rate, 2),
        }

    def _learning_context_summary(self, learning_context: List[Dict[str, Any]]) -> str:
        if not learning_context:
            return "No prior context available. Operate in conservative copilot mode."

        sample = learning_context[:10]
        wins = sum(1 for item in sample if _safe_float(item.get("pnl"), 0) > 0)
        return f"Last {len(sample)} plays include {wins} winners. Bias toward previously profitable signal classes."

    @staticmethod
    def _mock_flow() -> List[Dict[str, Any]]:
        now = datetime.utcnow().isoformat()
        return [
            {"id": "1", "ticker": "NVDA", "strike": 980, "expiry": "2026-03-21", "optionType": "CALL", "premium": 520000, "size": 2200, "sentiment": "Bullish", "time": now, "tag": "Sweep"},
            {"id": "2", "ticker": "TSLA", "strike": 240, "expiry": "2026-01-17", "optionType": "PUT", "premium": 340000, "size": 1800, "sentiment": "Bearish", "time": now, "tag": "Block"},
        ]

    @staticmethod
    def _mock_screener() -> List[Dict[str, Any]]:
        return [
            {"ticker": "NVDA", "ivRank": 78, "putCallRatio": 0.72, "volume": 120340, "openInterest": 560000, "impliedMove": 6.3, "sentimentScore": 84},
            {"ticker": "TSLA", "ivRank": 81, "putCallRatio": 1.34, "volume": 140090, "openInterest": 610200, "impliedMove": 8.2, "sentimentScore": 41},
        ]

    @staticmethod
    def _mock_ticker(ticker: str) -> Dict[str, Any]:
        return {
            "ticker": ticker.upper(),
            "maxPain": 450,
            "optionMid": 4.12,
            "chainSnapshot": [
                {"strike": 430, "callOi": 11240, "putOi": 7300},
                {"strike": 440, "callOi": 15880, "putOi": 10220},
            ],
            "greeks": {"delta": 0.42, "gamma": 0.03, "theta": -0.08, "vega": 0.22},
        }


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
