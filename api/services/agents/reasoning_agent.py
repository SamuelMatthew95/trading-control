"""Reasoning agent: makes trading decisions using LLM analysis of signals.

DB routing:
  - is_db_available() is checked upfront in process().
  - DB mode: writes to agent_runs, cost_tracking, vector_memory via a real session.
  - Memory mode: stores everything in InMemoryStore, no DB session opened at all.
  - get_persistence_mode() is NOT used here; it always returned "auto" and was dead code.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text

from api.config import settings
from api.constants import (
    AGENT_REASONING,
    AGENT_TRUST_DEFAULT,
    AGENT_TRUST_MAX,
    AGENT_TRUST_MIN,
    DECISION_MODE_HYBRID,
    DECISION_MODE_LLM,
    DECISION_MODE_POLICY,
    KELLY_FRACTION_SCALE,
    LLM_FALLBACK_MODE_LOCAL_POLICY,
    LLM_FALLBACK_MODE_REJECT_SIGNAL,
    LLM_FALLBACK_MODE_USE_LAST_REFLECTION,
    LLM_TASK_PRICE_ANALYSIS,
    LLM_TASK_TRADE_EXECUTION,
    LLM_TIMEOUT_SECONDS,
    MAX_RISK_PER_TRADE_PCT,
    MIN_RR_RATIO,
    MODEL_LABEL_POLICY,
    NO_ORDER_ACTIONS,
    REACT_CRITIQUE_CONFIDENCE_THRESHOLD,
    REASONING_NODE,
    REASONING_TOOL_MIN_ALPHA,
    REDIS_KEY_AGENT_SUSPENDED,
    REDIS_KEY_AGENT_TRUST,
    REDIS_KEY_IC_WEIGHTS,
    REDIS_KEY_LLM_COST,
    REDIS_KEY_LLM_TOKENS,
    REDIS_KEY_SIGNAL_WEIGHT_SCALE,
    SOURCE_REASONING,
    STOP_LOSS_PCT,
    STREAM_AGENT_LOGS,
    STREAM_DECISIONS,
    STREAM_RISK_ALERTS,
    STREAM_SIGNALS,
    STREAM_SYSTEM_METRICS,
    TOOL_CORRELATION_CHECK,
    TOOL_FLAG_CONFLUENCE_LOADED,
    TOOL_GET_IC_WEIGHTS,
    TOOL_MACRO_REGIME,
    TOOL_NEWS_SENTIMENT,
    TOOL_ORDER_BOOK_DEPTH,
    TOOL_QUERY_SIMILAR_TRADES,
    TOOL_STREAM_CONFLUENCE,
    AgentAction,
    FieldName,
    PositionSide,
    ToolPhase,
)
from api.database import AsyncSessionFactory
from api.events.bus import DEFAULT_GROUP, EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
from api.schema_version import DB_SCHEMA_VERSION
from api.services.agent_heartbeat import write_heartbeat as _write_heartbeat
from api.services.agent_state import AgentStateRegistry
from api.services.agents.db_helpers import get_last_reflection, write_agent_log
from api.services.agents.prompts import (
    ADAPTIVE_TRADING_SYSTEM_PROMPT,
    DECISION_OUTPUT_CONTRACT,
    REASONING_CRITIQUE_PROMPT,
)
from api.services.agents.vector_helpers import (
    build_vector_literal,
    embed_text,
    search_vector_memory,
)
from api.services.decision_policy import decide_policy, get_policy_params
from api.services.execution.brokers.paper import PaperBroker
from api.services.llm_router import active_model_label, call_llm_with_system
from api.services.market_intel import (
    compute_cross_asset_correlation,
    fetch_macro_regime,
    fetch_news_sentiment,
    fetch_order_book_depth,
)
from api.services.prompt_assembly import build_runtime_prompt
from api.services.prompt_store import get_prompt_store
from api.services.redis_store import get_redis_store
from api.services.risk_filters import compute_dynamic_position_size
from api.services.tool_registry import ToolMetadata, get_tool_registry


class ReasoningAgent(BaseStreamConsumer):
    """Listens on the ``signals`` stream and publishes advisory decisions to ``decisions``.

    This agent is a validator, not a decider. It outputs reasoning_score + recommended action
    to STREAM_DECISIONS. The ExecutionEngine is the sole authority for BUY/SELL orders.
    """

    _heartbeat_agent_name = AGENT_REASONING

    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        redis_client,
        *,
        agent_state: AgentStateRegistry | None = None,
    ):
        super().__init__(
            bus,
            dlq,
            stream=STREAM_SIGNALS,
            group=DEFAULT_GROUP,
            consumer="reasoning-agent",
            agent_state=agent_state,
        )
        self.redis = redis_client
        # PaperBroker is the position source of truth the ExecutionEngine uses
        # for its SELL reject; the agent reads the same source so it never
        # recommends (or advertises in the feed) selling a symbol we don't hold.
        self.broker = PaperBroker(redis_client)
        # Set by _call_llm to the provider:model actually used (incl. fallback);
        # consumed by process() to stamp model_used. None means "use configured
        # default". Safe as instance state: process() runs one event at a time.
        self._last_model_label: str | None = None
        # The tool invocations exercised during the current decision cycle —
        # {name, latency_ms, success} each. Reset at the top of process() and
        # attached to the decision so an operator can see the reasoning chain
        # ("this decision consulted these tools"), not just the final verdict.
        self._cycle_tools: list[dict[str, Any]] = []
        # Per-symbol monotonic timestamp of the last full reasoning cycle.
        # Enforces REASONING_COOLDOWN_SECONDS so a burst of repeat signals for
        # the same symbol does not fire one LLM call each — the dominant cause
        # of provider-quota burn. Safe as instance state: process() runs one
        # event at a time per consumer.
        self._last_reason_at: dict[str, float] = {}
        # Per-symbol fingerprint (side, price) of the last signal we actually
        # reasoned on. Lets us skip an LLM call when a fresh signal carries no
        # new information (same side, price within REASONING_DEDUP_PRICE_PCT).
        self._last_signal_fp: dict[str, tuple[str, float]] = {}

    async def process(self, data: dict[str, Any]) -> None:
        today = date.today().isoformat()
        trace_id = str(data.get(FieldName.TRACE_ID) or uuid.uuid4())

        # Learning-loop suspension — when ProposalApplier processes a Grade D
        # AGENT_SUSPENSION proposal, this key is set to "1" with a 24h TTL,
        # mirroring the kill-switch idiom. While set we drop incoming signals
        # so the bad reasoning agent stops emitting decisions.
        suspended_key = REDIS_KEY_AGENT_SUSPENDED.format(name=AGENT_REASONING)
        suspended_value = await self.redis.get(suspended_key)
        if suspended_value in ("1", b"1"):
            log_structured(
                "warning",
                "reasoning_skipped_agent_suspended",
                trace_id=trace_id,
                symbol=data.get(FieldName.SYMBOL),
            )
            return

        # Per-symbol reasoning cooldown — the dominant LLM-spend lever. Momentum
        # signals for one symbol can fire every few seconds; without this gate
        # each one woke a full LLM reasoning call (plus a self-critique call),
        # which burned the Groq quota. Within the window we drop the repeat
        # signal entirely (no LLM, no degraded-fallback decision); the next
        # signal after the window gets full reasoning. The base consumer's idle
        # heartbeat keeps the agent ACTIVE on the dashboard during skips.
        symbol = data.get(FieldName.SYMBOL)

        # Signal-change dedup — a fresh signal whose side AND price (within
        # REASONING_DEDUP_PRICE_PCT) match the last one we reasoned for this
        # symbol carries no new information, so skip the LLM call even outside
        # the cooldown window. 0 disables.
        dedup_pct = float(settings.REASONING_DEDUP_PRICE_PCT)
        if dedup_pct > 0 and symbol and self._is_duplicate_signal(symbol, data, dedup_pct):
            log_structured(
                "info",
                "reasoning_skipped_duplicate_signal",
                trace_id=trace_id,
                symbol=symbol,
            )
            return

        cooldown_s = float(settings.REASONING_COOLDOWN_SECONDS)
        if cooldown_s > 0 and symbol:
            now_mono = time.monotonic()
            last_at = self._last_reason_at.get(symbol)
            if last_at is not None and (now_mono - last_at) < cooldown_s:
                log_structured(
                    "info",
                    "reasoning_skipped_cooldown",
                    trace_id=trace_id,
                    symbol=symbol,
                    since_last_s=round(now_mono - last_at, 2),
                    cooldown_s=cooldown_s,
                )
                return
            self._last_reason_at[symbol] = now_mono

        # Committing to a full reasoning cycle — remember this signal so the
        # next identical one for the symbol can be deduped.
        if symbol:
            self._last_signal_fp[symbol] = self._signal_fingerprint(data)

        budget_used = int(await self.redis.get(REDIS_KEY_LLM_TOKENS.format(date=today)) or 0)
        # Reset per-decision provenance; _call_llm sets it to the real provider.
        self._last_model_label = None
        # Reset the per-cycle tool chain; _record_tool appends to it.
        self._cycle_tools = []

        # ReAct Step 1: Gather context (IC weights + risk state) before reasoning
        context = await self._gather_context(data)

        signal_summary = self._build_signal_summary(data)
        embedding = await embed_text(signal_summary)

        search_t0 = time.monotonic()
        search_ok = False
        try:
            similar_trades = await search_vector_memory(embedding)
            search_ok = True
        except Exception:
            log_structured("warning", "vector_memory_search_failed", exc_info=True)
            similar_trades = []
        # The reasoning node just exercised the memory-recall tool — fold its
        # real latency + reliability into the Tool Registry so the governance
        # panel and dead-tool suggestions reflect live usage, not just priors.
        self._record_tool(
            TOOL_QUERY_SIMILAR_TRADES,
            latency_ms=(time.monotonic() - search_t0) * 1000,
            success=search_ok,
            outputs={FieldName.COUNT: len(similar_trades)},
        )

        # --- Decision (routed by DECISION_MODE — Level-3 data/control split) ---
        summary, tokens_used, cost_usd, fallback_reason = await self._produce_decision(
            data, context, similar_trades, trace_id, budget_used
        )
        is_fallback = fallback_reason is not None

        # ReAct Step 2: Self-critique for high-confidence actionable decisions.
        # This is a SECOND LLM call per actionable decision; REASONING_SELF_CRITIQUE_ENABLED
        # gates it so the extra spend can be turned off when provider budget is tight.
        # Only runs when: enabled, not a fallback, action is buy/sell, confidence high enough,
        # and NOT in policy mode — the deterministic data plane must never touch the LLM, so a
        # policy decision is never sent for an LLM self-critique.
        action = str(summary.get(FieldName.ACTION, "")).lower()
        confidence = float(summary.get(FieldName.CONFIDENCE) or 0.0)
        if (
            settings.REASONING_SELF_CRITIQUE_ENABLED
            and settings.DECISION_MODE != DECISION_MODE_POLICY
            and not is_fallback
            and action not in NO_ORDER_ACTIONS
            and confidence >= REACT_CRITIQUE_CONFIDENCE_THRESHOLD
        ):
            try:
                critique_summary, critique_tokens, critique_cost = await asyncio.wait_for(
                    self._self_critique(summary, context, trace_id),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
                summary = critique_summary
                tokens_used += critique_tokens
                cost_usd += critique_cost
            except asyncio.TimeoutError:
                log_structured(
                    "warning",
                    "reasoning_critique_timeout",
                    trace_id=trace_id,
                    timeout=LLM_TIMEOUT_SECONDS,
                )

        # Enforce strict risk hierarchy before persistence/publishing.
        summary = self._apply_risk_hierarchy(summary, context)

        # Stamp the model that produced this decision so the learning loop
        # (GradeAgent / ReflectionAgent) can grade decisions with model
        # awareness. Prefer the provider actually used (captured by _call_llm,
        # incl. lmstudio→cloud fallback); fall back to the configured label.
        # Flows into agent_logs.step_data and the Redis decision record.
        if is_fallback:
            summary[FieldName.MODEL_USED] = "fallback"
        else:
            summary[FieldName.MODEL_USED] = self._last_model_label or active_model_label()

        # --- Persist agent run + cost tracking ---------------------------
        agent_run_id = await self._persist_run(
            data, summary, trace_id, is_fallback, today, tokens_used, cost_usd
        )

        # --- Agent log ---------------------------------------------------
        await write_agent_log(
            trace_id,
            "reasoning_summary",
            {**summary, FieldName.FALLBACK_REASON: fallback_reason, "source": SOURCE_REASONING},
            agent_run_id=agent_run_id,
        )

        # --- Vector memory (best-effort) ---------------------------------
        await self._persist_vector(signal_summary, embedding, summary)

        log_structured(
            "info", "reasoning_decision", trace_id=trace_id, action=summary.get(FieldName.ACTION)
        )

        # --- Heartbeat ---------------------------------------------------
        await _write_heartbeat(
            self.redis,
            AGENT_REASONING,
            f"action={summary.get(FieldName.ACTION)} symbol={data.get(FieldName.SYMBOL)}",
        )

        # --- Redis cost tracking -----------------------------------------
        await self.redis.incrby(REDIS_KEY_LLM_TOKENS.format(date=today), tokens_used)
        await self.redis.incrbyfloat(REDIS_KEY_LLM_COST.format(date=today), cost_usd)

        try:
            current_cost = float(await self.redis.get(REDIS_KEY_LLM_COST.format(date=today)) or 0.0)
            await self.bus.publish(
                STREAM_SYSTEM_METRICS,
                {
                    "type": "system_metric",
                    FieldName.METRIC_NAME: "llm_cost_today",
                    FieldName.VALUE: current_cost,
                    "source": SOURCE_REASONING,
                },
            )
        except Exception:
            log_structured("warning", "reasoning_cost_metric_publish_failed", exc_info=True)

        updated_budget = int(await self.redis.get(REDIS_KEY_LLM_TOKENS.format(date=today)) or 0)
        if updated_budget >= settings.ANTHROPIC_DAILY_TOKEN_BUDGET:
            await self.bus.publish(
                STREAM_RISK_ALERTS,
                {
                    "type": "llm_budget",
                    "message": "Daily LLM token budget exceeded",
                    FieldName.TOKENS_USED: updated_budget,
                    FieldName.LIMIT: settings.ANTHROPIC_DAILY_TOKEN_BUDGET,
                },
            )

        _edge = str(summary.get(FieldName.PRIMARY_EDGE) or "")
        _action = str(summary.get(FieldName.ACTION) or "hold")
        _conf = float(summary.get(FieldName.CONFIDENCE) or 0.0)
        await self.bus.publish(
            STREAM_AGENT_LOGS,
            {
                "type": "agent_log",
                "msg_id": str(uuid.uuid4()),
                "source": SOURCE_REASONING,
                "agent_name": AGENT_REASONING,
                FieldName.CONFIDENCE_SCORE: _conf * 100.0,
                FieldName.REASONING: _edge or "reasoning decision",
                # Explicit message for thought stream — frontend reads log.message first
                "message": f"{_action.upper()} ({_conf:.0%}) — {_edge}"
                if _edge
                else f"{_action.upper()} ({_conf:.0%})",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **summary,
            },
        )

        # --- Publish advisory decision to STREAM_DECISIONS ------------------
        # ReasoningAgent is advisory only — ExecutionEngine makes the final call.
        # Always publish regardless of action so ExecutionEngine can compute the
        # weighted score (signal_confidence * 0.50 + reasoning_score * 0.30 + perf * 0.20).
        action = summary.get(FieldName.ACTION, "").lower()
        strategy_id = str(data.get(FieldName.STRATEGY_ID) or uuid.uuid4())

        # Apply the learning-loop weight scale: ProposalApplier multiplies
        # this by 0.7 each time GradeAgent emits a Grade C proposal, so a
        # losing strategy's decisions get progressively dampened until they
        # fall below the execution gate. Default 1.0 = no dampening.
        weight_scale = await self._get_signal_weight_scale()
        # Behavioral promotion (opt-in): a sustained-high-grade ReasoningAgent has
        # its influence boosted, a struggling one damped, via the per-agent trust
        # weight. Bounded by AGENT_TRUST_MIN/MAX. Off by default — no live-trading
        # change unless an operator enables AGENT_TRUST_WEIGHTING_ENABLED.
        if settings.AGENT_TRUST_WEIGHTING_ENABLED:
            trust = await self._get_agent_trust(AGENT_REASONING)
            weight_scale = self._apply_trust_weighting(weight_scale, trust)
        scaled_reasoning = float(summary.get(FieldName.CONFIDENCE) or 0.0) * weight_scale
        scaled_signal = (
            float(data.get(FieldName.COMPOSITE_SCORE) or data.get(FieldName.CONFIDENCE) or 0.0)
            * weight_scale
        )

        await self.bus.publish(
            STREAM_DECISIONS,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.SOURCE: SOURCE_REASONING,
                FieldName.STRATEGY_ID: strategy_id,
                FieldName.SIGNAL_ID: str(
                    data.get(FieldName.SIGNAL_ID) or data.get(FieldName.MSG_ID) or ""
                ),
                FieldName.SYMBOL: data.get(FieldName.SYMBOL),
                FieldName.ACTION: action,
                # Advisory scores — ExecutionEngine uses these in weighted formula
                FieldName.REASONING_SCORE: round(scaled_reasoning, 6),
                FieldName.SIGNAL_CONFIDENCE: round(scaled_signal, 6),
                FieldName.WEIGHT_SCALE: round(weight_scale, 6),
                # Order parameters forwarded for ExecutionEngine use.
                # QTY carries a nominal unit count; the execution engine converts
                # SIZE_PCT (Kelly fraction) to an actual share count using live
                # portfolio value, so QTY and SIZE_PCT must not be mixed here.
                FieldName.QTY: float(data.get(FieldName.QTY) or 1.0),
                FieldName.PRICE: float(
                    data.get(FieldName.PRICE, data.get(FieldName.LAST_PRICE, 0.0))
                ),
                "session_id": strategy_id,
                FieldName.TIMESTAMP: data.get(
                    FieldName.TIMESTAMP, datetime.now(timezone.utc).isoformat()
                ),
                FieldName.TRACE_ID: trace_id,
                FieldName.PRIMARY_EDGE: summary.get(FieldName.PRIMARY_EDGE, ""),
                FieldName.RISK_FACTORS: summary.get(FieldName.RISK_FACTORS, []),
                # Why an action was downgraded (e.g. SELL→HOLD with no open long),
                # so the feed shows the reason instead of a silently-vanished SELL.
                FieldName.DOWNGRADE_REASON: str(summary.get(FieldName.DOWNGRADE_REASON) or ""),
                FieldName.MODEL_USED: summary.get(FieldName.MODEL_USED, ""),
                # LLM cost of this decision (incl. self-critique). Travels with
                # the trade so the learning loop can compute per-model net ROI.
                FieldName.DECISION_COST_USD: cost_usd,
                FieldName.SIZE_PCT: self._compute_kelly_position_size(summary),
                FieldName.STOP_ATR_X: float(summary.get(FieldName.STOP_ATR_X) or 1.5),
                FieldName.RR_RATIO: max(
                    float(summary.get(FieldName.RR_RATIO) or MIN_RR_RATIO), MIN_RR_RATIO
                ),
            },
        )
        log_structured(
            "info",
            "reasoning_dispatch_published",
            trace_id=trace_id,
            stream=STREAM_DECISIONS,
            action=action,
        )

        # Persist a Redis-backed decision record so the dashboard's recent
        # decisions panel works without a DB. Best-effort — Redis is required
        # for streams anyway, but we never let this fail the agent.
        await self._record_decision_to_redis(
            data=data,
            summary=summary,
            trace_id=trace_id,
            action=action,
            is_fallback=is_fallback,
        )

    _ACTIONABLE_ACTIONS: frozenset[str] = frozenset({AgentAction.BUY, AgentAction.SELL})

    @staticmethod
    def _is_fallback_decision(
        *,
        is_fallback: bool,
        payload: dict[str, Any],
        summary: dict[str, Any],
    ) -> bool:
        if is_fallback:
            return True
        llm_succeeded = payload.get(FieldName.LLM_SUCCEEDED)
        if llm_succeeded is False:
            return True

        reasoning_summary = str(payload.get(FieldName.REASONING_SUMMARY) or "").lower()
        reason = str(
            summary.get(FieldName.FALLBACK_REASON) or summary.get(FieldName.REASON) or ""
        ).lower()
        source = str(summary.get(FieldName.SOURCE) or "").lower()
        return "fallback" in reasoning_summary or "fallback" in reason or source == "fallback"

    def _compute_kelly_position_size(self, summary: dict) -> float:
        """Compute Kelly-fraction position size capped at MAX_RISK_PER_TRADE_PCT.

        Falls back to the LLM-suggested size_pct if Kelly produces zero
        (e.g., negative-EV scenario already caught by confidence gate).
        """
        confidence = float(summary.get(FieldName.CONFIDENCE) or 0.0)
        rr_ratio = max(float(summary.get(FieldName.RR_RATIO) or MIN_RR_RATIO), MIN_RR_RATIO)
        stop_loss = STOP_LOSS_PCT  # 5% stop from constants
        take_profit = stop_loss * rr_ratio  # enforce at least 2:1 R/R

        kelly_size = compute_dynamic_position_size(
            confidence=confidence,
            stop_loss_pct=stop_loss,
            take_profit_pct=take_profit,
            kelly_scale=KELLY_FRACTION_SCALE,
            max_risk_pct=MAX_RISK_PER_TRADE_PCT,
        )
        if kelly_size > 0:
            return kelly_size

        # Fallback: use LLM suggestion but cap it at max risk
        llm_size = float(summary.get(FieldName.SIZE_PCT) or 0.01)
        return min(llm_size, MAX_RISK_PER_TRADE_PCT)

    @staticmethod
    def _build_decision_payload(
        *,
        data: dict[str, Any],
        summary: dict[str, Any],
        trace_id: str,
        action: str,
        is_fallback: bool,
        tools_used: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Pure builder for the Redis decision payload — easy to test.

        `tools_used` is the cycle's tool ledger ({name, latency_ms, success,
        outputs}). Persisting it onto the decision makes the reasoning chain a
        first-class part of the decision object: an operator can see which tools
        produced the verdict, not just the verdict.
        """
        symbol = str(data.get(FieldName.SYMBOL) or "")
        price = data.get(FieldName.PRICE) or data.get(FieldName.LAST_PRICE)
        edge = str(summary.get(FieldName.PRIMARY_EDGE) or "")
        confidence = float(summary.get(FieldName.CONFIDENCE) or 0.0)
        return {
            FieldName.TRACE_ID: trace_id,
            FieldName.ACTION: action,
            FieldName.SYMBOL: symbol,
            FieldName.PRICE: price,
            FieldName.CONFIDENCE: confidence,
            FieldName.REASONING_SUMMARY: edge,
            FieldName.LLM_SUCCEEDED: not is_fallback,
            FieldName.TOOLS_USED: tools_used or [],
            FieldName.DOWNGRADE_REASON: str(summary.get(FieldName.DOWNGRADE_REASON) or ""),
        }

    @staticmethod
    def _build_decision_notification(
        *,
        action: str,
        symbol: str,
        price: Any,
        trace_id: str,
        is_fallback: bool,
        reason: str = "",
    ) -> dict[str, Any]:
        """Pure builder for the user-facing buy/sell notification payload."""
        price_str = ""
        if isinstance(price, (int, float)) and price:
            price_str = f" at ${float(price):,.2f}"
        if is_fallback:
            return {
                FieldName.TYPE: "fallback_trade_blocked",
                "title": f"Fallback {action.upper()} decision — {symbol}",
                "body": f"Degraded fallback decision for {symbol}: {reason or 'fallback_detected'}",
                "severity": "warning",
                "notification_type": "decision_degraded",
                "original_action": action,
                FieldName.SYMBOL: symbol,
                FieldName.ACTION: AgentAction.HOLD,
                FieldName.TRACE_ID: trace_id,
                "reason": reason or "fallback_detected",
                FieldName.LLM_SUCCEEDED: False,
            }
        return {
            FieldName.TYPE: "trade_signal",
            "title": f"{action.upper()} signal — {symbol}",
            "body": f"Reasoning agent decided to {action} {symbol}{price_str}",
            "severity": "info",
            FieldName.SYMBOL: symbol,
            FieldName.ACTION: action,
            FieldName.TRACE_ID: trace_id,
            FieldName.LLM_SUCCEEDED: True,
        }

    async def _record_decision_to_redis(
        self,
        *,
        data: dict[str, Any],
        summary: dict[str, Any],
        trace_id: str,
        action: str,
        is_fallback: bool,
    ) -> None:
        store = get_redis_store()
        if store is None:
            return
        payload = self._build_decision_payload(
            data=data,
            summary=summary,
            trace_id=trace_id,
            action=action,
            is_fallback=is_fallback,
            tools_used=self._cycle_tools,
        )
        persisted_decision = await store.push_decision(payload)
        if not is_db_available():
            # Record the persisted payload so in-memory and Redis copies share
            # the same canonical id/timestamp and dedupe key material.
            get_runtime_store().record_decision(persisted_decision)

        # Surface actionable buys/sells as notifications (one per decision,
        # not per fill). The execution layer still publishes the fill
        # notification separately, but this guarantees something appears on
        # the dashboard even before the order executes.
        if action in self._ACTIONABLE_ACTIONS:
            decision_is_fallback = self._is_fallback_decision(
                is_fallback=is_fallback,
                payload=payload,
                summary=summary,
            )
            notification = self._build_decision_notification(
                action=action,
                symbol=str(payload[FieldName.SYMBOL]),
                price=payload[FieldName.PRICE],
                trace_id=trace_id,
                is_fallback=decision_is_fallback,
                reason=str(
                    summary.get(FieldName.FALLBACK_REASON)
                    or summary.get(FieldName.PRIMARY_EDGE)
                    or ""
                ),
            )
            persisted = await store.push_notification(notification)
            if not is_db_available():
                # Record the persisted payload so in-memory and Redis copies use
                # the same id/timestamp and dedupe keys.
                get_runtime_store().record_notification(persisted)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_signal_weight_scale(self) -> float:
        """Read learning:signal_weight_scale; default 1.0 if absent or malformed.

        Written by ProposalApplier in response to Grade C proposals. Bounded
        in (0, 1] — never amplifies, only dampens. A return value of 1.0
        means the learning loop has not yet asked us to reduce weights.
        """
        try:
            raw = await self.redis.get(REDIS_KEY_SIGNAL_WEIGHT_SCALE)
            if raw is None:
                return 1.0
            scale = float(raw)
            if scale <= 0 or scale > 1.0:
                return 1.0
            return scale
        except (TypeError, ValueError):
            return 1.0
        except Exception:
            log_structured("warning", "reasoning_weight_scale_fetch_failed", exc_info=True)
            return 1.0

    @staticmethod
    def _apply_trust_weighting(weight_scale: float, trust: float) -> float:
        """Fold the per-agent trust multiplier into the signal weight scale.

        Trust (already bounded to [AGENT_TRUST_MIN, AGENT_TRUST_MAX]) only caps
        total influence at the top (AGENT_TRUST_MAX) — it must NEVER raise a
        Grade-C-dampened scale upward, or trust weighting would silently undo the
        learning loop's signal reductions. Result stays in (0, AGENT_TRUST_MAX].
        """
        return min(weight_scale * trust, AGENT_TRUST_MAX)

    async def _get_agent_trust(self, agent_name: str) -> float:
        """Read learning:agent_trust:{name}; default 1.0, bounded [MIN, MAX].

        Written by the promotion-apply action from the agent's grade tier. Unlike
        signal_weight_scale this CAN exceed 1.0 (a promoted agent gains influence),
        so it is bounded by AGENT_TRUST_MAX to cap amplification.
        """
        try:
            raw = await self.redis.get(REDIS_KEY_AGENT_TRUST.format(name=agent_name))
            if raw is None:
                return AGENT_TRUST_DEFAULT
            return min(max(float(raw), AGENT_TRUST_MIN), AGENT_TRUST_MAX)
        except (TypeError, ValueError):
            return AGENT_TRUST_DEFAULT
        except Exception:
            log_structured("warning", "reasoning_agent_trust_fetch_failed", exc_info=True)
            return AGENT_TRUST_DEFAULT

    def _build_signal_summary(self, data: dict[str, Any]) -> str:
        return json.dumps(
            {
                FieldName.SYMBOL: data.get(FieldName.SYMBOL),
                FieldName.PRICE: data.get(FieldName.PRICE),
                "composite_score": data.get(FieldName.COMPOSITE_SCORE),
                # Signal publishes "type" (e.g. "STRONG_MOMENTUM"); some callers use "signal_type"
                "signal_type": data.get(FieldName.SIGNAL_TYPE) or data.get(FieldName.TYPE),
                FieldName.CONTEXT: data.get(FieldName.CONTEXT, {}),
            },
            sort_keys=True,
            default=str,
        )

    def _signal_fingerprint(self, data: dict[str, Any]) -> tuple[str, float]:
        """(side, price) identity of a signal — the basis for dedup."""
        side = str(
            data.get(FieldName.ACTION)
            or data.get(FieldName.SIDE)
            or data.get(FieldName.SIGNAL)
            or ""
        ).lower()
        price = float(data.get(FieldName.PRICE) or 0.0)
        return side, price

    def _is_duplicate_signal(self, symbol: str, data: dict[str, Any], dedup_pct: float) -> bool:
        """True when this signal matches the last-reasoned one for the symbol —
        same side and price within ``dedup_pct`` percent."""
        prev = self._last_signal_fp.get(symbol)
        if not prev:
            return False
        prev_side, prev_price = prev
        side, price = self._signal_fingerprint(data)
        if side != prev_side or prev_price <= 0:
            return False
        return abs(price - prev_price) / prev_price <= (dedup_pct / 100.0)

    async def _gather_context(self, data: dict[str, Any]) -> dict[str, Any]:
        """ReAct context gathering: fetch IC weights and derive risk state from signal.

        This is the 'Observe' step — the agent collects environmental state before
        deciding, rather than reasoning in a vacuum.
        """
        context: dict[str, Any] = {}

        # Fetch live IC factor weights from Redis (written by ICUpdater). This is
        # the reasoning node's MEMORY tool `get_ic_weights`; time it and record
        # the call so its telemetry is live in the governance panel.
        ic_t0 = time.monotonic()
        ic_ok = False
        try:
            ic_raw = await self.redis.get(REDIS_KEY_IC_WEIGHTS)
            if ic_raw:
                context[FieldName.IC_WEIGHTS] = json.loads(ic_raw)
            ic_ok = True
        except Exception:
            log_structured("warning", "reasoning_ic_weights_fetch_failed", exc_info=True)
        self._record_tool(
            TOOL_GET_IC_WEIGHTS,
            latency_ms=(time.monotonic() - ic_t0) * 1000,
            success=ic_ok,
            outputs={FieldName.IC_WEIGHTS: context.get(FieldName.IC_WEIGHTS) or {}},
        )

        # Live market-intel perception tools — each gated on its registry
        # enabled flag, so when governance disables a dead tool the agent stops
        # paying for its fetch (closing the loop), and each records telemetry so
        # the grade loop can attribute realized PnL back to it.
        symbol = data.get(FieldName.SYMBOL)
        # Portfolio awareness: current open-long qty from the PaperBroker (the
        # same source the ExecutionEngine rejects against). Feeds the SELL guard
        # in _apply_risk_hierarchy so a SELL for a flat symbol becomes HOLD
        # instead of polluting the feed with an order that can never execute.
        context[FieldName.OPEN_POSITION_QTY] = await self._open_long_qty(symbol)
        if symbol:
            await self._gather_market_intel(symbol, context)

        # The self-evolving adaptive directive (learned guidance the learning
        # loop refines and an approved PROMPT_EVOLUTION proposal writes). Sits
        # beneath the immutable constitution at assembly time. Best-effort: a
        # missing store/directive just means we reason on the constitution alone.
        directive = await self._get_adaptive_directive()
        if directive:
            context[FieldName.PROMPT_VARIANT] = directive

        # Derive risk state from the signal itself
        context[FieldName.RISK_STATE] = {
            "composite_score": float(data.get(FieldName.COMPOSITE_SCORE) or 0.0),
            FieldName.MOMENTUM_PCT: float(data.get(FieldName.PCT) or 0.0),
            FieldName.SIGNAL_STRENGTH: data.get(FieldName.STRENGTH, "NORMAL"),
            "signal_type": data.get(FieldName.TYPE) or data.get(FieldName.SIGNAL_TYPE, "UNKNOWN"),
        }

        # Cross-stream confluence: the composite score SignalGenerator folds from
        # multiple market streams is already on the signal, so record the
        # confluence tool as exercised (gated on its registry flag, like the other
        # perception tools). Without this it would sit in tool governance as a
        # permanent seeded prior despite informing every reasoning decision.
        if self._tool_enabled(TOOL_STREAM_CONFLUENCE):
            composite = data.get(FieldName.COMPOSITE_SCORE)
            self._record_tool(
                TOOL_STREAM_CONFLUENCE,
                latency_ms=0.0,  # already in the signal payload — no fetch
                success=composite is not None,
                outputs={
                    FieldName.COMPOSITE_SCORE: float(composite or 0.0),
                    FieldName.SIGNAL_TYPE: data.get(FieldName.TYPE)
                    or data.get(FieldName.SIGNAL_TYPE, "UNKNOWN"),
                },
            )

        log_structured(
            "info",
            "reasoning_context_gathered",
            has_ic_weights=bool(context.get(FieldName.IC_WEIGHTS)),
            signal_type=context[FieldName.RISK_STATE][FieldName.SIGNAL_TYPE],
        )
        return context

    async def _open_long_qty(self, symbol: str | None) -> float:
        """Open LONG quantity for *symbol* per the PaperBroker (0.0 if flat/unknown).

        Best-effort and robust to a non-dict broker reply: portfolio awareness
        must never break a decision. Long-only — a flat / short / absent position
        returns 0.0, which the SELL guard reads as "nothing to sell".
        """
        if not symbol:
            return 0.0
        try:
            position = await self.broker.get_position(symbol)
        except Exception:
            log_structured(
                "warning", "reasoning_position_fetch_failed", symbol=symbol, exc_info=True
            )
            return 0.0
        if not isinstance(position, dict):
            return 0.0
        side = str(position.get(FieldName.SIDE) or "").lower()
        try:
            qty = float(position.get(FieldName.QTY) or 0.0)
        except (TypeError, ValueError):
            qty = 0.0
        return qty if (side == PositionSide.LONG and qty > 0) else 0.0

    @staticmethod
    def _tool_enabled(name: str) -> bool:
        """Whether the registry currently has this tool enabled (governance gate)."""
        tool = get_tool_registry().get(name)
        return bool(tool and tool.enabled)

    @staticmethod
    async def _get_adaptive_directive() -> str | None:
        """The active learned directive for the reasoning node, or None.

        Best-effort: no store installed, no directive, or a Redis hiccup all
        degrade to None so the decision runs on the constitution alone.
        """
        store = get_prompt_store()
        if store is None:
            return None
        try:
            return await store.get_active_text(REASONING_NODE)
        except Exception:
            log_structured("warning", "reasoning_adaptive_directive_fetch_failed", exc_info=True)
            return None

    async def _gather_market_intel(self, symbol: str, context: dict[str, Any]) -> None:
        """Invoke the live perception tools (order-book / news / correlation / macro-regime).

        Each is best-effort and individually gated on its registry enabled flag.
        Results land in ``context`` (fed to the LLM prompt) and each invocation
        is recorded so its latency/reliability — and, after the trade closes,
        its realized-PnL alpha — show up in tool governance.
        """
        intel: list[tuple[str, str, Any]] = [
            (TOOL_ORDER_BOOK_DEPTH, FieldName.ORDER_BOOK, fetch_order_book_depth(symbol)),
            (
                TOOL_NEWS_SENTIMENT,
                FieldName.NEWS_SENTIMENT,
                fetch_news_sentiment(symbol, self.redis),
            ),
            (
                TOOL_CORRELATION_CHECK,
                FieldName.CORRELATION,
                compute_cross_asset_correlation(symbol, self.redis),
            ),
            (TOOL_MACRO_REGIME, FieldName.MACRO_REGIME, fetch_macro_regime(symbol, self.redis)),
        ]
        for tool_name, ctx_key, coro in intel:
            if not self._tool_enabled(tool_name):
                coro.close()  # not eligible — don't pay for the fetch
                continue
            t0 = time.monotonic()
            result: dict[str, Any] = {}
            # success == the call COMPLETED without raising, NOT "returned data".
            # These intel tools are best-effort: an empty dict means "no data to
            # report this cycle" (e.g. no correlatable peer bars), a data-
            # availability fact — not a tool failure. Counting empty-as-error made
            # a perfectly-functioning tool read as 100% err on the governance panel.
            # This mirrors the `search_ok` / `ic_ok` convention the memory tools
            # above already use; the tool's *value* is captured separately by its
            # realized-PnL alpha, not by the failure rate.
            tool_ok = True
            try:
                result = await coro
            except Exception:
                tool_ok = False
                log_structured(
                    "warning", "reasoning_market_intel_failed", tool=tool_name, exc_info=True
                )
            if result:
                context[ctx_key] = result
            self._record_tool(
                tool_name,
                latency_ms=(time.monotonic() - t0) * 1000,
                success=tool_ok,
                outputs=result,
            )

    # ------------------------------------------------------------------
    # Prompt-OS: tool-governed runtime prompt assembly + tool telemetry
    # ------------------------------------------------------------------

    def _record_tool(
        self,
        name: str,
        *,
        latency_ms: float,
        success: bool,
        outputs: dict[str, Any] | None = None,
    ) -> None:
        """Fold one reasoning-node tool invocation into the Tool Registry.

        Best-effort and outcome-agnostic: telemetry must never break a trading
        decision, and realized PnL is unknown at decision time, so alpha
        attribution stays at its prior until the grade loop reports an outcome.

        `outputs` is a small decision-relevant summary of what the tool returned
        (e.g. how many similar trades, the IC weights) — never raw blobs — so the
        decision's tool ledger is self-explanatory.
        """
        # Capture the invocation on the per-cycle chain first so the decision
        # records which tools it used even if the aggregate registry write below
        # raises. Cheap and never throws.
        self._cycle_tools.append(
            {
                FieldName.NAME: name,
                FieldName.LATENCY_MS: round(latency_ms, 1),
                FieldName.SUCCESS: success,
                FieldName.OUTPUTS: outputs or {},
            }
        )
        try:
            get_tool_registry().record_call(name, latency_ms=latency_ms, success=success)
        except Exception:
            log_structured("warning", "tool_telemetry_record_failed", tool=name, exc_info=True)

    @staticmethod
    def _reasoning_state_flags(data: dict[str, Any], context: dict[str, Any]) -> set[str]:
        """State flags satisfied at the reasoning node — gate which tools unlock.

        The signal carries cross-stream confluence (composite_score), so the
        confluence-dependent tools become eligible. Risk-approval and
        thesis-commit flags belong to the downstream execution node and are
        never set here, so execution tools can never leak into reasoning.
        """
        flags: set[str] = set()
        if data.get(FieldName.COMPOSITE_SCORE) is not None or context.get(FieldName.IC_WEIGHTS):
            flags.add(TOOL_FLAG_CONFLUENCE_LOADED)
        return flags

    def _select_reasoning_tools(
        self, data: dict[str, Any], context: dict[str, Any]
    ) -> list[ToolMetadata]:
        """The eligible perception + memory tools the buy/sell LLM may see.

        Negative-alpha tools are filtered (REASONING_TOOL_MIN_ALPHA) so dead
        weight like a negative-edge sector scan never reaches the prompt — even
        while it stays registered for the operator's attribution view.
        """
        flags = self._reasoning_state_flags(data, context)
        registry = get_tool_registry()
        tools = registry.select_tools(
            ToolPhase.PERCEPTION,
            available_state_flags=flags,
            min_alpha=REASONING_TOOL_MIN_ALPHA,
        )
        tools += registry.select_tools(
            ToolPhase.MEMORY,
            available_state_flags=flags,
            min_alpha=REASONING_TOOL_MIN_ALPHA,
        )
        return tools

    @staticmethod
    def _reasoning_regime(context: dict[str, Any]) -> str:
        risk_state = context.get(FieldName.RISK_STATE) or {}
        return str(risk_state.get(FieldName.SIGNAL_STRENGTH) or "unknown").lower()

    def _assemble_decision_prompt(
        self,
        data: dict[str, Any],
        context: dict[str, Any],
        similar_trades: list[dict[str, Any]],
    ) -> str:
        """Constitution + node-scoped tools + compact context + output contract.

        Falls back to the static adaptive prompt if assembly ever raises, so a
        registry hiccup can never block a decision.
        """
        try:
            active_tools = self._select_reasoning_tools(data, context)
            risk_state = context.get(FieldName.RISK_STATE) or {}
            ic_weights = context.get(FieldName.IC_WEIGHTS) or {}
            portfolio_summary = (
                f"score={risk_state.get(FieldName.COMPOSITE_SCORE, 'n/a')} "
                f"momentum={risk_state.get(FieldName.MOMENTUM_PCT, 'n/a')} "
                f"strength={risk_state.get(FieldName.SIGNAL_STRENGTH, 'NORMAL')}"
            )
            telemetry_summary = (
                f"ic_factors={sorted(ic_weights)[:5] or 'none'}; "
                f"similar_trades={len(similar_trades)} recalled"
            )
            runtime_prompt = build_runtime_prompt(
                node=REASONING_NODE,
                active_tools=active_tools,
                regime=self._reasoning_regime(context),
                portfolio_summary=portfolio_summary,
                telemetry_summary=telemetry_summary,
                # The learned, self-evolving directive — assembled beneath the
                # immutable constitution. None → constitution-only prompt.
                challenger_variant=context.get(FieldName.PROMPT_VARIANT) or None,
            )
            return f"{runtime_prompt}\n\n{DECISION_OUTPUT_CONTRACT}"
        except Exception:
            log_structured(
                "warning", "reasoning_prompt_assembly_failed_using_static", exc_info=True
            )
            return ADAPTIVE_TRADING_SYSTEM_PROMPT

    async def _self_critique(
        self,
        decision: dict[str, Any],
        context: dict[str, Any],
        trace_id: str,
    ) -> tuple[dict[str, Any], int, float]:
        """ReAct self-critique: the agent evaluates its own decision before acting.

        If the critique finds the decision unjustified, it applies the recommended
        action and confidence. Falls back to the original decision on any error.
        Returns (decision, tokens_used, cost_usd).
        """
        try:
            critique_prompt = json.dumps(
                {
                    FieldName.DECISION: decision,
                    FieldName.IC_WEIGHTS: context.get(FieldName.IC_WEIGHTS, {}),
                    FieldName.RISK_STATE: context.get(FieldName.RISK_STATE, {}),
                },
                default=str,
            )
            log_structured(
                "debug",
                "llm_prompt_sent",
                trace_id=trace_id,
                call_type="critique",
                prompt_chars=len(critique_prompt),
                prompt_preview=critique_prompt[:400],
                system_prompt_preview=REASONING_CRITIQUE_PROMPT[:200],
            )
            raw_text, tokens, cost = await call_llm_with_system(
                critique_prompt,
                REASONING_CRITIQUE_PROMPT,
                trace_id,
                task_type=LLM_TASK_PRICE_ANALYSIS,
            )
            log_structured(
                "debug",
                "llm_response_received",
                trace_id=trace_id,
                call_type="critique",
                tokens=tokens,
                cost_usd=cost,
                response_chars=len(str(raw_text)),
                response_raw=str(raw_text)[:600],
            )
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
                if "\n" in cleaned:
                    first, rest = cleaned.split("\n", 1)
                    if first.strip() in {"json", "JSON", ""}:
                        cleaned = rest
                if cleaned.rstrip().endswith("```"):
                    cleaned = cleaned.rstrip()[:-3].strip()
            critique = json.loads(cleaned)
            log_structured(
                "debug",
                "llm_response_parsed",
                trace_id=trace_id,
                call_type="critique",
                justified=critique.get(FieldName.JUSTIFIED),
                recommended_action=critique.get(FieldName.RECOMMENDED_ACTION),
                concerns=critique.get(FieldName.CONCERNS, []),
            )

            log_structured(
                "info",
                "reasoning_self_critique_completed",
                trace_id=trace_id,
                justified=critique.get(FieldName.JUSTIFIED),
                concerns=critique.get(FieldName.CONCERNS, []),
                original_action=decision.get(FieldName.ACTION),
                recommended_action=critique.get(FieldName.RECOMMENDED_ACTION),
            )

            # Apply critique only when it explicitly flags the decision as unjustified
            if not critique.get(FieldName.JUSTIFIED, True):
                rec_action = str(
                    critique.get(FieldName.RECOMMENDED_ACTION) or decision[FieldName.ACTION]
                ).lower()
                rec_confidence = float(
                    critique.get(FieldName.RECOMMENDED_CONFIDENCE) or decision[FieldName.CONFIDENCE]
                )
                refined = {
                    **decision,
                    FieldName.ACTION: rec_action,
                    "confidence": round(rec_confidence, 4),
                    FieldName.RISK_FACTORS: list(decision.get(FieldName.RISK_FACTORS) or [])
                    + [
                        c
                        for c in critique.get(FieldName.CONCERNS, [])
                        if c not in (decision.get(FieldName.RISK_FACTORS) or [])
                    ],
                }
                return refined, tokens, cost

            return decision, tokens, cost

        except Exception:
            log_structured(
                "warning",
                "reasoning_critique_failed_using_original",
                trace_id=trace_id,
                exc_info=True,
            )
            return decision, 0, 0.0

    async def _call_llm(
        self,
        data: dict[str, Any],
        similar_trades: list[dict[str, Any]],
        trace_id: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int, float]:
        # Select token budget: strong directional signals warrant deeper reasoning
        signal_type = str(data.get(FieldName.SIGNAL_TYPE) or data.get(FieldName.TYPE) or "").upper()
        composite_score = float(data.get(FieldName.COMPOSITE_SCORE) or 0.0)
        task_type = (
            LLM_TASK_TRADE_EXECUTION
            if ("STRONG" in signal_type or composite_score >= 0.75)
            else LLM_TASK_PRICE_ANALYSIS
        )

        risk_state = (context or {}).get(FieldName.RISK_STATE) or {
            "status": "nominal",
            "current_drawdown_pct": 0.0,
            "global_veto": False,
        }
        ic_weights = (context or {}).get(FieldName.IC_WEIGHTS) or {"composite_score": 1.0}
        similar_trades_payload = similar_trades or []
        if not similar_trades_payload:
            # No memory matches: bias to smaller sizing while preserving direction signal context.
            risk_state.setdefault("size_pct_scale", 0.5)

        ctx = context or {}
        prompt = json.dumps(
            {
                "signal": data,
                FieldName.SIMILAR_TRADES: similar_trades_payload,
                FieldName.IC_WEIGHTS: ic_weights,
                FieldName.RISK_STATE: risk_state,
                # Live market-intel from the perception tools, when present.
                FieldName.ORDER_BOOK: ctx.get(FieldName.ORDER_BOOK) or {},
                FieldName.NEWS_SENTIMENT: ctx.get(FieldName.NEWS_SENTIMENT) or {},
                FieldName.CORRELATION: ctx.get(FieldName.CORRELATION) or {},
                FieldName.MACRO_REGIME: ctx.get(FieldName.MACRO_REGIME) or {},
                FieldName.SYSTEM_DIRECTIVE: "CAPITAL_PRESERVATION_FIRST",
            },
            default=str,
        )
        # Dynamic runtime prompt (Prompt-OS): immutable constitution + ONLY the
        # node-scoped tools the registry deems eligible + compact context, with
        # the JSON output contract appended. This is what makes the buy/sell LLM
        # actually "use tools" — it sees the governed subset, never the catalog.
        system_prompt = self._assemble_decision_prompt(data, context or {}, similar_trades_payload)
        log_structured(
            "debug",
            "llm_prompt_sent",
            trace_id=trace_id,
            call_type="decision",
            task_type=task_type,
            prompt_chars=len(prompt),
            prompt_preview=prompt[:400],
            system_prompt_preview=system_prompt[:200],
        )
        meta: dict[str, Any] = {}
        raw_text, tokens, cost_usd = await call_llm_with_system(
            prompt, system_prompt, trace_id, task_type=task_type, result_meta=meta
        )
        # Record the provider:model actually used (incl. lmstudio→cloud fallback)
        # so model attribution stays accurate, not just the configured default.
        self._last_model_label = meta.get("model_label")
        log_structured(
            "debug",
            "llm_response_received",
            trace_id=trace_id,
            call_type="decision",
            tokens=tokens,
            cost_usd=cost_usd,
            response_chars=len(str(raw_text)),
            response_raw=str(raw_text)[:600],
        )
        if isinstance(raw_text, dict):
            return raw_text, tokens, cost_usd

        cleaned = str(raw_text).strip()
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
            if "\n" in cleaned:
                first, rest = cleaned.split("\n", 1)
                if first.strip() in {"json", "JSON", ""}:
                    cleaned = rest
            if cleaned.rstrip().endswith("```"):
                cleaned = cleaned.rstrip()[:-3].strip()
        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                raise json.JSONDecodeError("LLM JSON must be an object", cleaned, 0)
            log_structured(
                "debug",
                "llm_response_parsed",
                trace_id=trace_id,
                call_type="decision",
                action=parsed.get(FieldName.ACTION),
                confidence=parsed.get(FieldName.CONFIDENCE),
                primary_edge=str(parsed.get(FieldName.PRIMARY_EDGE, ""))[:120],
                risk_factors=parsed.get(FieldName.RISK_FACTORS, []),
            )
        except json.JSONDecodeError:
            log_structured(
                "warning",
                "llm_response_invalid_json",
                trace_id=trace_id,
                call_type="decision",
                cleaned_preview=cleaned[:300],
            )
            parsed = {
                FieldName.ACTION: AgentAction.HOLD,
                FieldName.CONFIDENCE: 0.0,
                FieldName.PRIMARY_EDGE: "invalid_json",
                FieldName.RISK_FACTORS: ["invalid_llm_json"],
                FieldName.SIZE_PCT: 0.01,
                FieldName.STOP_ATR_X: 1.5,
                FieldName.RR_RATIO: 2.0,
            }
        return parsed, tokens, cost_usd

    def _apply_risk_hierarchy(
        self, decision: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Enforce capital-preservation-first decision hierarchy."""
        safe_decision = dict(decision)
        risk_factors = list(safe_decision.get(FieldName.RISK_FACTORS) or [])
        action = str(safe_decision.get(FieldName.ACTION, AgentAction.HOLD)).lower()

        # 0) Position validity — never recommend selling a symbol we don't hold.
        # Long-only: a SELL only makes sense to close an open long, so when flat
        # we downgrade to HOLD (tagged with a reason) instead of advertising a
        # SELL in the feed that the ExecutionEngine would reject. The engine
        # still enforces the same rule as a backstop (reject_unmatched_sell).
        open_long_qty = float(context.get(FieldName.OPEN_POSITION_QTY) or 0.0)
        if action == AgentAction.SELL and open_long_qty <= 0:
            safe_decision[FieldName.ACTION] = AgentAction.HOLD
            safe_decision[FieldName.DOWNGRADE_REASON] = "sell_without_open_long"
            if "NO_OPEN_POSITION" not in risk_factors:
                risk_factors.append("NO_OPEN_POSITION")
            safe_decision[FieldName.RISK_FACTORS] = risk_factors
            return safe_decision

        # 1) Capital preservation hard stop.
        drawdown = float(context.get(FieldName.RISK_STATE, {}).get(FieldName.DRAWDOWN) or 0.0)
        if drawdown <= -0.15:
            safe_decision[FieldName.ACTION] = AgentAction.HOLD
            safe_decision[FieldName.CONFIDENCE] = 0.0
            if "MAX_DRAWDOWN_EXCEEDED" not in risk_factors:
                risk_factors.append("MAX_DRAWDOWN_EXCEEDED")
            safe_decision[FieldName.RISK_FACTORS] = risk_factors
            return safe_decision

        # 2) IC alignment check.
        if not self._ic_aligns(action, context.get(FieldName.IC_WEIGHTS, {}), safe_decision):
            safe_decision[FieldName.ACTION] = AgentAction.HOLD
            safe_decision[FieldName.CONFIDENCE] = round(
                float(safe_decision.get(FieldName.CONFIDENCE) or 0.0) * 0.3, 4
            )
            if "IC_MISALIGNMENT" not in risk_factors:
                risk_factors.append("IC_MISALIGNMENT")
            safe_decision[FieldName.RISK_FACTORS] = risk_factors
            return safe_decision

        # 3) Consensus threshold.
        agreement_ratio = float(safe_decision.get(FieldName.AGREEMENT_RATIO) or 1.0)
        if agreement_ratio < 0.5:
            safe_decision[FieldName.ACTION] = AgentAction.HOLD
            if "LOW_CONSENSUS" not in risk_factors:
                risk_factors.append("LOW_CONSENSUS")
            safe_decision[FieldName.RISK_FACTORS] = risk_factors

        return safe_decision

    def _compute_kelly_position_size(self, summary: dict[str, Any]) -> float:
        """Compute Kelly-fraction position size capped at MAX_RISK_PER_TRADE_PCT.

        Falls back to the LLM-suggested size_pct if Kelly produces zero
        (negative-EV scenario should already be caught by the confidence gate).
        """
        confidence = float(summary.get(FieldName.CONFIDENCE) or 0.0)
        rr_ratio = max(float(summary.get(FieldName.RR_RATIO) or MIN_RR_RATIO), MIN_RR_RATIO)
        take_profit = STOP_LOSS_PCT * rr_ratio

        kelly_size = compute_dynamic_position_size(
            confidence=confidence,
            stop_loss_pct=STOP_LOSS_PCT,
            take_profit_pct=take_profit,
            kelly_scale=KELLY_FRACTION_SCALE,
            max_risk_pct=MAX_RISK_PER_TRADE_PCT,
        )
        if kelly_size > 0:
            return kelly_size

        llm_size = float(summary.get(FieldName.SIZE_PCT) or 0.01)
        return min(llm_size, MAX_RISK_PER_TRADE_PCT)

    def _ic_aligns(
        self, signal_direction: str, ic_weights: dict[str, float], decision: dict[str, Any]
    ) -> bool:
        """Check whether action direction aligns with dominant IC weight."""
        if not ic_weights:
            return True
        try:
            factor_name, _weight = max(ic_weights.items(), key=lambda item: float(item[1]))
        except Exception:
            return True

        if factor_name != "composite_score":
            return True

        score = float(
            decision.get(FieldName.COMPOSITE_SCORE) or decision.get(FieldName.CONFIDENCE) or 0.0
        )
        direction = signal_direction.lower()
        if score > 0.5:
            return direction in {AgentAction.BUY, "long"}
        return direction in {AgentAction.SELL, AgentAction.HOLD, "short", "flat"}

    async def _produce_decision(
        self,
        data: dict[str, Any],
        context: dict[str, Any],
        similar_trades: list[dict[str, Any]],
        trace_id: str,
        budget_used: int,
    ) -> tuple[dict[str, Any], int, float, str | None]:
        """Route the per-signal decision by DECISION_MODE (data/control-plane split).

        Returns ``(summary, tokens_used, cost_usd, fallback_reason)``.

        - ``policy``: the deterministic data-plane policy decides — no LLM on the
          critical path, always available.
        - ``llm`` (default): the LLM decides; the policy runs in SHADOW so we can
          measure agreement before trusting policy-primary. LLM failure degrades
          per the configured fallback.
        - ``hybrid``: LLM-primary, but the policy is the always-on safety net on
          any LLM failure (never goes dark), regardless of LLM_FALLBACK_MODE.
        """
        mode = settings.DECISION_MODE

        # Data-plane primary — deterministic, no external call on the hot path.
        if mode == DECISION_MODE_POLICY:
            self._last_model_label = MODEL_LABEL_POLICY
            summary = decide_policy(data, context, get_policy_params())
            # Shape-complete the summary like the LLM/fallback paths so the decision
            # record + dashboard are consistent (instant + free, a real decision).
            summary.update(
                {
                    FieldName.TRACE_ID: trace_id,
                    FieldName.LATENCY_MS: 0,
                    FieldName.COST_USD: 0.0,
                    FieldName.FALLBACK: False,
                }
            )
            return summary, 0, 0.0, None

        # Budget exhausted before any call — degrade per mode.
        if budget_used >= settings.ANTHROPIC_DAILY_TOKEN_BUDGET:
            summary = await self._degrade(data, context, trace_id, "budget_exceeded")
            return summary, 0, 0.0, "budget_exceeded"

        # LLM-primary (llm | hybrid).
        try:
            summary, tokens_used, cost_usd = await asyncio.wait_for(
                self._call_llm(data, similar_trades, trace_id, context),
                timeout=LLM_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            log_structured(
                "warning", "reasoning_llm_timeout", trace_id=trace_id, timeout=LLM_TIMEOUT_SECONDS
            )
            summary = await self._degrade(data, context, trace_id, "llm_timeout")
            return summary, 0, 0.0, "llm_timeout"
        except Exception as exc:  # noqa: BLE001
            summary = await self._degrade(data, context, trace_id, str(exc))
            return summary, 0, 0.0, str(exc)

        # llm mode: validate the deterministic policy against the live LLM call.
        if mode == DECISION_MODE_LLM:
            self._shadow_compare_policy(summary, data, context, trace_id)
        return summary, tokens_used, cost_usd, None

    async def _degrade(
        self, data: dict[str, Any], context: dict[str, Any], trace_id: str, reason: str
    ) -> dict[str, Any]:
        """Decision when the LLM cannot answer.

        ``hybrid`` always uses the deterministic policy (a real decision, never
        dark); other modes honour the configured ``LLM_FALLBACK_MODE``.
        """
        if settings.DECISION_MODE == DECISION_MODE_HYBRID:
            decision = decide_policy(data, context or {}, get_policy_params())
            decision[FieldName.RISK_FACTORS] = [
                *decision.get(FieldName.RISK_FACTORS, []),
                reason,
            ]
            decision[FieldName.PRIMARY_EDGE] = f"hybrid_fallback:{reason}"
            decision.update(
                {
                    FieldName.LATENCY_MS: 0,
                    FieldName.COST_USD: 0.0,
                    FieldName.TRACE_ID: trace_id,
                    FieldName.FALLBACK: True,
                }
            )
            return decision
        return await self._apply_fallback(data, trace_id, reason=reason, context=context)

    def _shadow_compare_policy(
        self,
        llm_summary: dict[str, Any],
        data: dict[str, Any],
        context: dict[str, Any],
        trace_id: str,
    ) -> None:
        """Run the deterministic policy in SHADOW beside the live LLM decision and
        log agreement — zero-risk evidence for promoting DECISION_MODE=policy."""
        try:
            policy = decide_policy(data, context, get_policy_params())
            llm_action = str(llm_summary.get(FieldName.ACTION, "")).lower()
            policy_action = str(policy.get(FieldName.ACTION, "")).lower()
            log_structured(
                "info",
                "decision_shadow_compare",
                trace_id=trace_id,
                llm_action=llm_action,
                policy_action=policy_action,
                agree=llm_action == policy_action,
            )
        except Exception:
            log_structured(
                "warning", "decision_shadow_compare_failed", trace_id=trace_id, exc_info=True
            )

    async def _apply_fallback(
        self,
        data: dict[str, Any],
        trace_id: str,
        reason: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Level-3 data plane: when configured, the deterministic local policy
        # decides instead of rejecting — so the LLM being down/throttled stops
        # taking the whole pipeline dark. The policy is fast, explainable, and
        # always available; the LLM's role moves to tuning its params (control
        # plane), off this critical path.
        if settings.LLM_FALLBACK_MODE == LLM_FALLBACK_MODE_LOCAL_POLICY:
            decision = decide_policy(data, context or {}, get_policy_params())
            decision[FieldName.RISK_FACTORS] = [
                *decision.get(FieldName.RISK_FACTORS, []),
                reason,
            ]
            decision[FieldName.PRIMARY_EDGE] = f"fallback:{LLM_FALLBACK_MODE_LOCAL_POLICY}"
            decision.update(
                {
                    FieldName.LATENCY_MS: 0,
                    FieldName.COST_USD: 0.0,
                    FieldName.TRACE_ID: trace_id,
                    FieldName.FALLBACK: True,
                }
            )
            return decision

        base_action = str(
            data.get(FieldName.ACTION) or data.get(FieldName.SIGNAL) or AgentAction.HOLD
        ).lower()
        signal_direction = str(data.get(FieldName.DIRECTION) or "").lower()
        if base_action in {"none", "", AgentAction.HOLD}:
            if signal_direction in {"bullish", AgentAction.BUY, "long"}:
                base_action = AgentAction.BUY
            elif signal_direction in {"bearish", AgentAction.SELL, "short"}:
                base_action = AgentAction.SELL
            else:
                pct = float(data.get(FieldName.PCT) or 0.0)
                if pct > 0:
                    base_action = AgentAction.BUY
                elif pct < 0:
                    base_action = AgentAction.SELL
                else:
                    base_action = AgentAction.HOLD
        composite_score = float(data.get(FieldName.COMPOSITE_SCORE, 0.0) or 0.0)

        if settings.LLM_FALLBACK_MODE == LLM_FALLBACK_MODE_REJECT_SIGNAL:
            action = AgentAction.REJECT
        elif settings.LLM_FALLBACK_MODE == LLM_FALLBACK_MODE_USE_LAST_REFLECTION:
            reflection = await get_last_reflection()
            action = reflection.get(FieldName.ACTION, base_action) if reflection else base_action
            valid_actions = {
                AgentAction.BUY,
                AgentAction.SELL,
                AgentAction.HOLD,
                AgentAction.REJECT,
            }
            if action not in valid_actions:
                action = base_action if base_action not in {"none", ""} else AgentAction.HOLD
        else:
            action = base_action if base_action not in {"none", ""} else AgentAction.HOLD

        return {
            FieldName.ACTION: action,
            FieldName.CONFIDENCE: round(max(composite_score, 0.1), 4),
            FieldName.PRIMARY_EDGE: f"fallback:{settings.LLM_FALLBACK_MODE}",
            FieldName.RISK_FACTORS: [reason],
            FieldName.SIZE_PCT: round(
                max(float(data.get(FieldName.SIZE_PCT, 0.01) or 0.01), 0.01), 4
            ),
            FieldName.STOP_ATR_X: float(data.get(FieldName.STOP_ATR_X, 1.5) or 1.5),
            FieldName.RR_RATIO: float(data.get(FieldName.RR_RATIO, 2.0) or 2.0),
            FieldName.LATENCY_MS: 0,
            FieldName.COST_USD: 0.0,
            FieldName.TRACE_ID: trace_id,
            FieldName.FALLBACK: True,
        }

    # ------------------------------------------------------------------
    # Unified persistence — single routing point per operation
    # ------------------------------------------------------------------

    async def _persist_run(
        self,
        data: dict[str, Any],
        summary: dict[str, Any],
        trace_id: str,
        is_fallback: bool,
        today: str,
        tokens_used: int,
        cost_usd: float,
    ) -> str:
        """Persist agent run and cost tracking. Routes DB vs memory, returns agent_run_id."""
        if is_db_available():
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    agent_run_id = await self._db_store_agent_run(
                        data, summary, trace_id, is_fallback, session
                    )
                    await self._db_store_cost_tracking(today, tokens_used, cost_usd, session)
            return agent_run_id
        return self._mem_store_agent_run(data, summary, trace_id, is_fallback)

    async def _persist_vector(
        self, signal_summary: str, embedding: list[float], summary: dict[str, Any]
    ) -> None:
        """Persist vector memory entry. Routes DB vs memory."""
        if is_db_available():
            try:
                async with AsyncSessionFactory() as vm_session:
                    async with vm_session.begin():
                        await self._db_store_vector_memory(
                            signal_summary, embedding, summary, vm_session
                        )
            except Exception:
                log_structured("warning", "vector_memory_insert_failed", exc_info=True)
        else:
            self._mem_store_vector_memory(signal_summary, embedding, summary)

    # --- DB path helpers (only called when is_db_available() is True) ---

    async def _db_store_agent_run(
        self,
        data: dict[str, Any],
        summary: dict[str, Any],
        trace_id: str,
        fallback: bool,
        session,
    ) -> str:
        result = await session.execute(
            text("""
                INSERT INTO agent_runs (
                    strategy_id, symbol, signal_data, action, confidence,
                    primary_edge, risk_factors, size_pct, stop_atr_x, rr_ratio,
                    latency_ms, cost_usd, trace_id, fallback,
                    source, schema_version, status
                ) VALUES (
                    :strategy_id, :symbol, :signal_data, :action, :confidence,
                    :primary_edge, :risk_factors, :size_pct, :stop_atr_x,
                    :rr_ratio, :latency_ms, :cost_usd, :trace_id, :fallback,
                    :source, :schema_version, 'running'
                ) RETURNING id
            """),
            {
                FieldName.STRATEGY_ID: data.get(FieldName.STRATEGY_ID),
                FieldName.SYMBOL: data.get(FieldName.SYMBOL),
                FieldName.SIGNAL_DATA: json.dumps(data, default=str),
                FieldName.ACTION: summary[FieldName.ACTION],
                FieldName.CONFIDENCE: summary[FieldName.CONFIDENCE],
                FieldName.PRIMARY_EDGE: summary[FieldName.PRIMARY_EDGE],
                FieldName.RISK_FACTORS: json.dumps(summary[FieldName.RISK_FACTORS], default=str),
                FieldName.SIZE_PCT: summary[FieldName.SIZE_PCT],
                FieldName.STOP_ATR_X: summary[FieldName.STOP_ATR_X],
                FieldName.RR_RATIO: summary[FieldName.RR_RATIO],
                FieldName.LATENCY_MS: summary[FieldName.LATENCY_MS],
                FieldName.COST_USD: summary[FieldName.COST_USD],
                FieldName.TRACE_ID: trace_id,
                FieldName.FALLBACK: fallback,
                FieldName.SOURCE: AGENT_REASONING,
                FieldName.SCHEMA_VERSION: DB_SCHEMA_VERSION,
            },
        )
        return str(result.scalar_one())

    async def _db_store_cost_tracking(
        self, today: str, tokens_used: int, cost_usd: float, session
    ) -> None:
        try:
            await session.execute(
                text("""
                    INSERT INTO llm_cost_tracking (date, tokens_used, cost_usd)
                    VALUES (:date, :tokens_used, :cost_usd) RETURNING id
                """),
                {FieldName.DATE: today, FieldName.TOKENS_USED: tokens_used, "cost_usd": cost_usd},
            )
        except Exception:
            log_structured("warning", "cost_tracking_insert_failed", exc_info=True)

    async def _db_store_vector_memory(
        self, content: str, embedding: list[float], summary: dict[str, Any], session
    ) -> None:
        await session.execute(
            text("""
                INSERT INTO vector_memory (content, embedding, metadata_, outcome)
                VALUES (
                    :content,
                    CAST(:embedding AS vector),
                    CAST(:metadata AS JSONB),
                    CAST(:outcome AS JSONB)
                ) RETURNING id
            """),
            {
                "content": content,
                "embedding": build_vector_literal(embedding),
                "metadata": json.dumps({"trace_id": summary[FieldName.TRACE_ID]}),
                "outcome": json.dumps(
                    {
                        "action": summary[FieldName.ACTION],
                        "confidence": summary[FieldName.CONFIDENCE],
                    }
                ),
            },
        )

    # --- Memory path helpers (only called when is_db_available() is False) ---

    def _mem_store_agent_run(
        self,
        data: dict[str, Any],
        summary: dict[str, Any],
        trace_id: str,
        fallback: bool,
    ) -> str:
        run_id = f"mem-{trace_id}"
        get_runtime_store().add_agent_run(
            {
                FieldName.ID: run_id,
                FieldName.TRACE_ID: trace_id,
                FieldName.SYMBOL: data.get(FieldName.SYMBOL),
                FieldName.ACTION: summary.get(FieldName.ACTION),
                "confidence": summary.get(FieldName.CONFIDENCE),
                FieldName.FALLBACK: fallback,
                FieldName.SOURCE: AGENT_REASONING,
                FieldName.STATUS: "running",
            }
        )
        return run_id

    def _mem_store_vector_memory(
        self, content: str, embedding: list[float], summary: dict[str, Any]
    ) -> None:
        get_runtime_store().add_vector_memory(
            {
                "content": content,
                "embedding": embedding,
                "metadata": {FieldName.TRACE_ID: summary.get(FieldName.TRACE_ID)},
                "outcome": {
                    FieldName.ACTION: summary.get(FieldName.ACTION),
                    "confidence": summary.get(FieldName.CONFIDENCE),
                },
            }
        )
