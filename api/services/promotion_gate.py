"""Promotion gate (Prompt-OS Layer 4 + challenger promotion).

Ties the replay harness, the deterministic regression validator, and the
strategy-registry lifecycle together: a challenger version advances exactly one
lifecycle stage ONLY if (1) the regression replay passes every hard gate AND
(2) the lifecycle transition is legal. A challenger configuration can never
alter a live execution path without clearing this gate.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel

from api.constants import TOOL_REPLAY_REGRESSION, StrategyStatus
from api.observability import log_structured
from api.services.regression_validator import RegressionValidator, RegressionVerdict
from api.services.replay_harness import ReplayHarness, ReplayMetrics
from api.services.strategy_registry import (
    InvalidTransitionError,
    StrategyRegistry,
    get_strategy_registry,
)
from api.services.tool_registry import get_tool_registry


class PromotionDecision(BaseModel):
    version_id: str
    to_status: StrategyStatus
    approved: bool
    transitioned: bool
    reason: str
    champion: ReplayMetrics
    candidate: ReplayMetrics
    verdict: RegressionVerdict


class PromotionGate:
    """Gatekeeper for advancing a strategy version through the lifecycle."""

    def __init__(
        self,
        *,
        registry: StrategyRegistry | None = None,
        harness: ReplayHarness | None = None,
        validator: RegressionValidator | None = None,
    ) -> None:
        self._registry = registry or get_strategy_registry()
        self._harness = harness or ReplayHarness()
        self._validator = validator or RegressionValidator()

    def evaluate(
        self,
        version_id: str,
        *,
        champion_trades: list[dict[str, Any]],
        candidate_trades: list[dict[str, Any]],
        to_status: StrategyStatus,
    ) -> PromotionDecision:
        """Replay both sides, validate, and promote only if it clears every gate."""
        _replay_t0 = time.monotonic()
        champion = self._harness.replay(champion_trades)
        candidate = self._harness.replay(candidate_trades)
        verdict = self._validator.validate(champion, candidate)
        # Optimization-phase tool telemetry: the regression replay ran. Folds the
        # replay_regression tool into governance (latency + reliability) so the
        # OPTIMIZATION phase is live, not a permanent seeded prior.
        try:
            get_tool_registry().record_call(
                TOOL_REPLAY_REGRESSION,
                latency_ms=(time.monotonic() - _replay_t0) * 1000,
                success=True,
            )
        except Exception:
            log_structured("warning", "replay_tool_telemetry_failed", exc_info=True)

        transitioned = False
        if not verdict.approved:
            reason = "rejected: " + "; ".join(verdict.reasons)
        else:
            try:
                self._registry.transition(version_id, to_status)
                transitioned = True
                reason = f"promoted to {to_status.value}"
            except InvalidTransitionError as exc:
                reason = f"regression passed but transition blocked: {exc}"

        log_structured(
            "info",
            "promotion_evaluated",
            version_id=version_id,
            to_status=to_status.value,
            approved=verdict.approved,
            transitioned=transitioned,
        )
        return PromotionDecision(
            version_id=version_id,
            to_status=to_status,
            approved=verdict.approved,
            transitioned=transitioned,
            reason=reason,
            champion=champion,
            candidate=candidate,
            verdict=verdict,
        )
