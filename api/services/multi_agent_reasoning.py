"""Reasoning-model adapters for the multi-agent orchestrator."""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

from api.constants import FieldName
from api.observability import log_structured
from api.utils import get_nested

try:
    import anthropic
except ImportError:  # pragma: no cover - dependency optional in tests
    anthropic = None

from api.services.multi_agent_models import Direction


class ReasoningModel(Protocol):
    def complete_json(self, *, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class AnthropicReasoningModel:
    def __init__(
        self,
        api_key: str,
        *,
        model_name: str = "claude-sonnet-4-20250514",
        retries: int = 2,
    ):
        if anthropic is None:
            raise RuntimeError("anthropic package is not installed")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model_name = model_name
        self.retries = retries

    def complete_json(self, *, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.client.messages.create(
                    model=self.model_name,
                    max_tokens=1024,
                    system=system_prompt,
                    messages=[{FieldName.ROLE: "user", "content": json.dumps(payload)}],
                )
                text = response.content[0].text
                return json.loads(text)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                log_structured(
                    "warning",
                    "reasoning model retry",
                    attempt=attempt + 1,
                    exc_info=True,
                )
                time.sleep(0.2 * (attempt + 1))
        raise RuntimeError(f"Model call failed after retries: {last_error}")


class DeterministicReasoningModel:
    """Fallback local model to keep flows deterministic in development/tests."""

    def complete_json(self, *, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        if "normalize trade signals" in system_prompt.lower():
            direction: Direction = (
                "LONG" if payload[FieldName.ASSET] in {"AAPL", "MSFT"} else "FLAT"
            )
            return [
                {
                    "source": "heuristic",
                    "direction": direction,
                    "confidence": 0.7,
                    FieldName.TIMEFRAME: payload[FieldName.TIMEFRAME],
                }
            ]
        if "compute consensus" in system_prompt.lower():
            signals = payload.get(FieldName.SIGNALS, [])
            if not signals:
                return {
                    "direction": "FLAT",
                    FieldName.AGREEMENT_RATIO: 0.0,
                    FieldName.SIGNAL_STRENGTH: 0.0,
                }
            direction = signals[0][FieldName.DIRECTION]
            agreement = sum(1 for s in signals if s[FieldName.DIRECTION] == direction) / len(
                signals
            )
            confidence = sum(float(s.get(FieldName.CONFIDENCE, 0)) for s in signals) / len(signals)
            return {
                "direction": direction,
                FieldName.AGREEMENT_RATIO: agreement,
                FieldName.SIGNAL_STRENGTH: round(agreement * confidence, 3),
            }
        if "enforce risk limits" in system_prompt.lower():
            drawdown = float(get_nested(payload, "portfolio", "drawdown", default=0))
            veto = drawdown < -0.15
            return {
                FieldName.APPROVED: not veto,
                FieldName.VETO: veto,
                FieldName.RISK_SCORE: min(1.0, abs(drawdown) * 2 + 0.1),
                FieldName.SIZE_MULTIPLIER: 0.5 if veto else 1.0,
                FieldName.FLAGS: ["MAX_DRAWDOWN"] if veto else [],
            }
        price = float(payload.get(FieldName.ASSET_PRICE, 100))
        atr = float(payload.get(FieldName.ATR, 5))
        return {
            FieldName.UNITS: int(
                max(1, payload.get(FieldName.PORTFOLIO_VALUE, 100000) * 0.01 / max(price, 1))
            ),
            FieldName.ENTRY: price,
            FieldName.STOP: max(0.01, price - atr),
            FieldName.TARGET: price + atr * 2,
            "rr_ratio": 2.0,
        }
