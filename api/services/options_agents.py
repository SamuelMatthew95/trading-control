from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List


@dataclass
class OptionsAgentOutput:
    """Standard envelope for agent-to-agent communication."""

    agent: str
    summary: str
    payload: Dict[str, Any]
    timestamp: datetime


class OptionsAnalystAgent:
    """Perception layer: converts raw flow + screener into normalized signal context."""

    def run(self, flow: List[Dict[str, Any]], screener: List[Dict[str, Any]]) -> OptionsAgentOutput:
        bullish = [row for row in flow if str(row.get("sentiment", "")).lower() == "bullish"]
        bearish = [row for row in flow if str(row.get("sentiment", "")).lower() == "bearish"]
        top_tags = Counter(str(row.get("tag", "Unknown")) for row in flow).most_common(3)
        top_tickers = Counter(str(row.get("ticker", "")).upper() for row in flow).most_common(5)
        screener_bias = [row for row in screener if _safe_float(row.get("sentimentScore"), 50) >= 60]

        return OptionsAgentOutput(
            agent="OPTIONS_ANALYST",
            summary=(
                f"Flow skew bullish={len(bullish)} bearish={len(bearish)}; "
                f"dominant tags={top_tags}; dominant tickers={top_tickers}."
            ),
            payload={
                "bullish_flow": len(bullish),
                "bearish_flow": len(bearish),
                "top_tags": top_tags,
                "top_tickers": top_tickers,
                "screener_bias_count": len(screener_bias),
            },
            timestamp=datetime.utcnow(),
        )


class OptionsStrategistAgent:
    """Planning layer: maps analyzed context to strategy candidates."""

    def run(self, analyst_payload: Dict[str, Any], screener: List[Dict[str, Any]]) -> OptionsAgentOutput:
        screener_by_ticker = {str(row.get("ticker", "")).upper(): row for row in screener}
        top_tags = analyst_payload.get("top_tags") or [["Unknown", 0]]
        primary_signal = top_tags[0][0]
        candidates: List[Dict[str, Any]] = []

        for ticker, _count in analyst_payload.get("top_tickers", []):
            row = screener_by_ticker.get(str(ticker).upper())
            if not row:
                continue

            sentiment_score = _safe_float(row.get("sentimentScore"), 50)
            put_call = _safe_float(row.get("putCallRatio"), 1)
            action = "Buy Call" if sentiment_score >= 60 and put_call <= 1 else "Buy Put"
            regime = "trend" if sentiment_score >= 60 else "mean-reversion"
            confidence_seed = min(max(sentiment_score / 100, 0.30), 0.90)

            candidates.append(
                {
                    "ticker": str(ticker).upper(),
                    "action": action,
                    "regime": regime,
                    "confidence_seed": round(confidence_seed, 2),
                    "signal_type": primary_signal,
                }
            )

        return OptionsAgentOutput(
            agent="OPTIONS_STRATEGIST",
            summary=f"Generated {len(candidates)} regime-aligned candidates.",
            payload={"candidates": candidates[:5]},
            timestamp=datetime.utcnow(),
        )


class OptionsExecutorAgent:
    """Action layer: creates executable trade candidates with limits and expiries."""

    def run(self, candidates: List[Dict[str, Any]], chain_lookup: Dict[str, Dict[str, Any]]) -> OptionsAgentOutput:
        plays: List[Dict[str, Any]] = []
        expiry = (datetime.utcnow().date() + timedelta(days=30)).isoformat()

        for candidate in candidates:
            ticker = str(candidate.get("ticker", "")).upper()
            snapshot = chain_lookup.get(ticker, {})
            option_mid = _safe_float(snapshot.get("optionMid"), 2.5)
            strike = _safe_float(snapshot.get("maxPain"), 100)
            confidence = _safe_float(candidate.get("confidence_seed"), 0.5)

            plays.append(
                {
                    "ticker": ticker,
                    "action": str(candidate.get("action", "Buy Call")),
                    "strike": round(strike, 2),
                    "expiry": expiry,
                    "reasoning": f"{candidate.get('regime', 'trend')} setup + {candidate.get('signal_type', 'Unknown')} flow confluence",
                    "confidence": round(confidence, 2),
                    "entry_price_estimate": round(option_mid, 2),
                    "target": round(option_mid * 1.8, 2),
                    "stop_loss": round(option_mid * 0.6, 2),
                    "signal_type": str(candidate.get("signal_type", "Unknown")),
                }
            )

        return OptionsAgentOutput(
            agent="OPTIONS_EXECUTOR",
            summary=f"Prepared {len(plays)} execution-ready plays with entry/target/stop anchors.",
            payload={"plays": plays[:5]},
            timestamp=datetime.utcnow(),
        )


class OptionsGuardrailAgent:
    """Risk/safety layer: enforces hard constraints and kill-switch behavior."""

    def run(self, plays: List[Dict[str, Any]]) -> OptionsAgentOutput:
        approved: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []

        for play in plays:
            confidence = _safe_float(play.get("confidence"), 0)
            entry = _safe_float(play.get("entry_price_estimate"), 0)
            stop = _safe_float(play.get("stop_loss"), 0)
            risk_per_contract = max(entry - stop, 0)

            if confidence < 0.55:
                rejected.append({**play, "reject_reason": "confidence_below_threshold"})
                continue
            if risk_per_contract > 10:
                rejected.append({**play, "reject_reason": "risk_per_contract_too_high"})
                continue

            approved.append({**play, "max_contracts": 1 if confidence < 0.70 else 2})

        return OptionsAgentOutput(
            agent="OPTIONS_GUARDRAIL",
            summary=f"Approved={len(approved)} Rejected={len(rejected)}",
            payload={"approved": approved, "rejected": rejected, "kill_switch": len(approved) == 0},
            timestamp=datetime.utcnow(),
        )


class OptionsValidatorAgent:
    """Validation layer: verifies schema/quality before the orchestrator returns output."""

    REQUIRED_FIELDS = {
        "ticker",
        "action",
        "strike",
        "expiry",
        "reasoning",
        "confidence",
        "entry_price_estimate",
        "target",
        "stop_loss",
    }

    def run(self, approved_plays: List[Dict[str, Any]]) -> OptionsAgentOutput:
        valid: List[Dict[str, Any]] = []
        dropped = 0

        for play in approved_plays:
            if not self.REQUIRED_FIELDS.issubset(play.keys()):
                dropped += 1
                continue
            if _safe_float(play.get("confidence"), 0) < 0.55:
                dropped += 1
                continue
            valid.append(play)

        return OptionsAgentOutput(
            agent="OPTIONS_VALIDATOR",
            summary=f"Validated={len(valid)} Dropped={dropped}",
            payload={"validated": valid, "dropped": dropped},
            timestamp=datetime.utcnow(),
        )


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
