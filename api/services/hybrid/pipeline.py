"""Hybrid decision pipeline orchestrator.

Composes the deterministic stages and the LLM agents into one flow and emits a
durable lifecycle event (decision_id-keyed) at every stage so the ledger /
dashboard can always explain why a trade happened or was blocked.

Guarantees:
  - The LLM is never called when market validation or the candidate gate fails.
  - The deterministic risk engine is the final authority; an LLM can never
    approve or place a trade.
  - Position sizing is deterministic.
  - The orchestrator never touches the broker. When ``publish_decisions`` is on
    it publishes an approved, sized decision to STREAM_DECISIONS for the
    existing ExecutionEngine — the only component allowed to place orders.
"""

from __future__ import annotations

import uuid
from typing import Any

from api.constants import (
    HYBRID_LIFECYCLE_EVENT_TYPE,
    SOURCE_HYBRID,
    STREAM_DECISIONS,
    STREAM_TRADE_LIFECYCLE,
    BlockReason,
    FieldName,
    LifecycleStage,
)
from api.observability import log_structured
from api.schema_version import DB_SCHEMA_VERSION
from api.services.hybrid.candidate_gate import build_candidate
from api.services.hybrid.config import HybridConfig
from api.services.hybrid.llm_decision import (
    LLMCall,
    request_instruct_decision,
    request_reasoning_review,
    should_run_reasoning,
)
from api.services.hybrid.market_validator import validate_market
from api.services.hybrid.models import (
    BrokerState,
    InstructDecision,
    MarketSnapshot,
    PipelineResult,
    PortfolioState,
    PositionState,
    ReasoningReview,
    RiskDecision,
    SignalCandidate,
    SignalSummary,
    SizedOrder,
)
from api.services.hybrid.position_sizing import size_position
from api.services.hybrid.risk_engine import evaluate_risk


class HybridDecisionPipeline:
    """Single entry point for a hybrid trading decision."""

    def __init__(
        self,
        bus: Any | None = None,
        *,
        config: HybridConfig | None = None,
        llm_call: LLMCall | None = None,
        publish_decisions: bool = False,
    ) -> None:
        self.bus = bus
        self.config = config or HybridConfig.from_settings()
        self._llm_call = llm_call
        self.publish_decisions = publish_decisions

    @property
    def llm_call(self) -> LLMCall:
        if self._llm_call is not None:
            return self._llm_call
        # Lazy default to the shared router so tests can inject a stub without
        # importing provider SDKs.
        from api.services.llm_router import call_llm_with_system  # noqa: PLC0415

        return call_llm_with_system

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def decide(
        self,
        *,
        market: MarketSnapshot,
        signal: SignalSummary,
        portfolio: PortfolioState,
        position: PositionState,
        broker: BrokerState,
        trace_id: str | None = None,
        decision_id: str | None = None,
        duplicate_signal: bool = False,
        idempotency_reused: bool = False,
    ) -> PipelineResult:
        trace_id = trace_id or str(uuid.uuid4())
        decision_id = decision_id or str(uuid.uuid4())
        symbol = market.symbol
        stages: list[LifecycleStage] = []

        await self._emit(
            LifecycleStage.SIGNAL_CREATED, decision_id, trace_id, symbol, "hold", signal
        )
        stages.append(LifecycleStage.SIGNAL_CREATED)

        # ---- Stage 1: deterministic market validation (pre-LLM) ----
        validation = validate_market(market, self.config)
        await self._emit(
            LifecycleStage.MARKET_VALIDATED, decision_id, trace_id, symbol, "hold", validation
        )
        stages.append(LifecycleStage.MARKET_VALIDATED)
        if not validation.passed:
            return await self._block(
                decision_id,
                trace_id,
                symbol,
                validation.block_reason,
                f"market_validation:{validation.block_reason}",
                stages,
                market=validation,
            )

        # ---- Stage 2: deterministic candidate gate (pre-LLM) ----
        candidate = build_candidate(signal, self.config)
        await self._emit(
            LifecycleStage.SIGNAL_CANDIDATE_CREATED,
            decision_id,
            trace_id,
            symbol,
            "hold",
            candidate,
        )
        stages.append(LifecycleStage.SIGNAL_CANDIDATE_CREATED)
        if not candidate.send_to_model:
            return await self._block(
                decision_id,
                trace_id,
                symbol,
                candidate.block_reason,
                f"candidate_gate:{candidate.block_reason}",
                stages,
                market=validation,
                candidate=candidate,
            )

        # ---- Stage 3: fast instruct decision (LLM) ----
        instruct, instruct_valid = await request_instruct_decision(
            self.llm_call,
            candidate=candidate,
            market=market,
            signal=signal,
            portfolio=portfolio,
            position=position,
            config=self.config,
            trace_id=trace_id,
        )
        await self._emit(
            LifecycleStage.MODEL_RECOMMENDED,
            decision_id,
            trace_id,
            symbol,
            instruct.action,
            instruct,
            confidence=instruct.confidence,
        )
        stages.append(LifecycleStage.MODEL_RECOMMENDED)

        # ---- Stage 4: reasoning review (LLM, only when needed) ----
        review: ReasoningReview | None = None
        reasoning_called = False
        if instruct_valid and should_run_reasoning(instruct, position, portfolio, self.config):
            review = await request_reasoning_review(
                self.llm_call,
                instruct=instruct,
                signal=signal,
                portfolio=portfolio,
                position=position,
                trace_id=trace_id,
            )
            reasoning_called = True
            await self._emit(
                LifecycleStage.REASONING_REVIEWED,
                decision_id,
                trace_id,
                symbol,
                review.final_model_action,
                review,
                confidence=review.confidence,
            )
            stages.append(LifecycleStage.REASONING_REVIEWED)

        # ---- Stage 5: deterministic risk engine (final authority) ----
        risk = evaluate_risk(
            instruct=instruct,
            review=review,
            portfolio=portfolio,
            position=position,
            broker=broker,
            config=self.config,
            current_price=market.last_price or 0.0,
            instruct_valid=instruct_valid,
            duplicate_signal=duplicate_signal,
            idempotency_reused=idempotency_reused,
        )

        if not risk.approved:
            # A plain hold (no block_reason) is a valid no-trade, not a block.
            if risk.block_reason is None:
                return self._result(
                    decision_id,
                    trace_id,
                    symbol,
                    "hold",
                    approved=False,
                    block_reason=None,
                    reason="hold",
                    stages=stages,
                    llm_called=True,
                    reasoning_called=reasoning_called,
                    market=validation,
                    candidate=candidate,
                    instruct=instruct,
                    review=review,
                    risk=risk,
                )
            await self._emit(
                LifecycleStage.RISK_BLOCKED,
                decision_id,
                trace_id,
                symbol,
                "hold",
                risk,
                block_reason=risk.block_reason,
            )
            stages.append(LifecycleStage.RISK_BLOCKED)
            return self._result(
                decision_id,
                trace_id,
                symbol,
                "hold",
                approved=False,
                block_reason=risk.block_reason,
                reason=f"risk:{risk.block_reason}",
                stages=stages,
                llm_called=True,
                reasoning_called=reasoning_called,
                market=validation,
                candidate=candidate,
                instruct=instruct,
                review=review,
                risk=risk,
            )

        await self._emit(
            LifecycleStage.RISK_APPROVED,
            decision_id,
            trace_id,
            symbol,
            risk.decision,
            risk,
            confidence=instruct.confidence,
        )
        stages.append(LifecycleStage.RISK_APPROVED)

        # ---- Stage 6: deterministic position sizing ----
        order = size_position(
            risk=risk,
            portfolio=portfolio,
            position=position,
            config=self.config,
            size_hint=instruct.position_size_hint,
        )
        if order.reject_reason is not None:
            await self._emit(
                LifecycleStage.RISK_BLOCKED,
                decision_id,
                trace_id,
                symbol,
                "hold",
                order,
                block_reason=order.reject_reason,
            )
            stages.append(LifecycleStage.RISK_BLOCKED)
            return self._result(
                decision_id,
                trace_id,
                symbol,
                "hold",
                approved=False,
                block_reason=order.reject_reason,
                reason=f"sizing:{order.reject_reason}",
                stages=stages,
                llm_called=True,
                reasoning_called=reasoning_called,
                market=validation,
                candidate=candidate,
                instruct=instruct,
                review=review,
                risk=risk,
                order=order,
            )

        await self._emit(
            LifecycleStage.ORDER_SIZED,
            decision_id,
            trace_id,
            symbol,
            order.side,
            order,
        )
        stages.append(LifecycleStage.ORDER_SIZED)

        # ---- Stage 7: hand off to ExecutionEngine (opt-in) ----
        if self.publish_decisions:
            await self._publish_decision(decision_id, trace_id, order, instruct, risk)
            await self._emit(
                LifecycleStage.ORDER_PENDING,
                decision_id,
                trace_id,
                symbol,
                order.side,
                order,
            )
            stages.append(LifecycleStage.ORDER_PENDING)

        return self._result(
            decision_id,
            trace_id,
            symbol,
            order.side,
            approved=True,
            block_reason=None,
            reason="approved",
            stages=stages,
            llm_called=True,
            reasoning_called=reasoning_called,
            market=validation,
            candidate=candidate,
            instruct=instruct,
            review=review,
            risk=risk,
            order=order,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _block(
        self,
        decision_id: str,
        trace_id: str,
        symbol: str,
        block_reason: BlockReason | None,
        reason: str,
        stages: list[LifecycleStage],
        *,
        market: Any = None,
        candidate: SignalCandidate | None = None,
    ) -> PipelineResult:
        """Emit a terminal RISK_BLOCKED lifecycle event and return a blocked result.

        Used for pre-LLM blocks (market validation / candidate gate). ``llm_called``
        stays False so the safety property "no LLM call on hard failure" holds.
        """
        await self._emit(
            LifecycleStage.RISK_BLOCKED,
            decision_id,
            trace_id,
            symbol,
            "hold",
            candidate,
            block_reason=block_reason,
        )
        stages.append(LifecycleStage.RISK_BLOCKED)
        return self._result(
            decision_id,
            trace_id,
            symbol,
            "hold",
            approved=False,
            block_reason=block_reason,
            reason=reason,
            stages=stages,
            llm_called=False,
            reasoning_called=False,
            market=market,
            candidate=candidate,
        )

    @staticmethod
    def _result(
        decision_id: str,
        trace_id: str,
        symbol: str,
        final_action: str,
        *,
        approved: bool,
        block_reason: BlockReason | None,
        reason: str,
        stages: list[LifecycleStage],
        llm_called: bool,
        reasoning_called: bool,
        market: Any = None,
        candidate: SignalCandidate | None = None,
        instruct: InstructDecision | None = None,
        review: ReasoningReview | None = None,
        risk: RiskDecision | None = None,
        order: SizedOrder | None = None,
    ) -> PipelineResult:
        return PipelineResult(
            decision_id=decision_id,
            trace_id=trace_id,
            symbol=symbol,
            final_action=final_action,
            approved=approved,
            block_reason=block_reason,
            reason=reason,
            stages=stages,
            llm_called=llm_called,
            reasoning_called=reasoning_called,
            market=market,
            candidate=candidate,
            instruct=instruct,
            review=review,
            risk=risk,
            order=order,
        )

    async def _emit(
        self,
        stage: LifecycleStage,
        decision_id: str,
        trace_id: str,
        symbol: str,
        action: str,
        payload_model: Any,
        *,
        block_reason: BlockReason | None = None,
        confidence: float | None = None,
    ) -> None:
        """Publish one durable lifecycle event to STREAM_TRADE_LIFECYCLE."""
        if self.bus is None:
            return
        event: dict[str, Any] = {
            FieldName.EVENT_TYPE: HYBRID_LIFECYCLE_EVENT_TYPE,
            FieldName.EVENT_VERSION: DB_SCHEMA_VERSION,
            FieldName.STAGE: stage.value,
            FieldName.DECISION_ID: decision_id,
            FieldName.TRACE_ID: trace_id,
            FieldName.SYMBOL: symbol,
            FieldName.ACTION: action,
            FieldName.PRODUCER: SOURCE_HYBRID,
            FieldName.SOURCE: SOURCE_HYBRID,
            FieldName.DATA: payload_model.model_dump(mode="json") if payload_model else {},
        }
        if block_reason is not None:
            event[FieldName.BLOCK_REASON] = block_reason.value
        if confidence is not None:
            event[FieldName.CONFIDENCE] = confidence
        try:
            await self.bus.publish(STREAM_TRADE_LIFECYCLE, event)
        except Exception:
            log_structured(
                "warning", "hybrid_lifecycle_emit_failed", stage=stage.value, exc_info=True
            )

    async def _publish_decision(
        self,
        decision_id: str,
        trace_id: str,
        order: SizedOrder,
        instruct: InstructDecision,
        risk: RiskDecision,
    ) -> None:
        """Publish an approved, sized decision for the ExecutionEngine to act on."""
        if self.bus is None:
            return
        decision: dict[str, Any] = {
            FieldName.MSG_ID: str(uuid.uuid4()),
            FieldName.DECISION_ID: decision_id,
            FieldName.TRACE_ID: trace_id,
            FieldName.SOURCE: SOURCE_HYBRID,
            FieldName.PRODUCER: SOURCE_HYBRID,
            FieldName.SYMBOL: order.symbol,
            FieldName.ACTION: order.side,
            FieldName.QTY: order.qty,
            FieldName.PRICE: order.entry,
            FieldName.SIGNAL_CONFIDENCE: instruct.confidence,
            FieldName.REASONING_SCORE: instruct.confidence,
            FieldName.STOP_PRICE: order.stop_loss,
            FieldName.TAKE_PROFIT_PRICE: order.take_profit,
            FieldName.SIZE_PCT: risk.size_multiplier,
        }
        try:
            await self.bus.publish(STREAM_DECISIONS, decision)
        except Exception:
            log_structured("warning", "hybrid_publish_decision_failed", exc_info=True)
