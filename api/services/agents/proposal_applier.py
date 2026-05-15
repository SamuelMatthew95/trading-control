"""ProposalApplier — closes the learning loop.

GradeAgent, ReflectionAgent, and StrategyProposer publish proposals to
``STREAM_PROPOSALS`` describing what should change in response to bad
performance: ``reduce_signal_weight``, ``suspend_from_live_stream``,
``retire_immediately``. Until this consumer existed, those proposals were
written to the DB and notifications stream and never acted on, so a
losing strategy could keep firing the same signals indefinitely.

This agent reads STREAM_PROPOSALS and translates each action into the
Redis control-plane keys that ExecutionEngine and ReasoningAgent read:

  reduce_signal_weight   -> multiply ``learning:signal_weight_scale`` by 0.7
  suspend_from_live_stream -> set ``learning:agent_suspended:{name}`` (24h TTL)
  retire_immediately     -> set ``learning:trading_paused`` = "1" (system-wide)

Every applied proposal is recorded as an ``agent_logs`` row with
``log_type=LogType.PROPOSAL`` and an ``applied_at`` field so the
dashboard can show pending vs applied at a glance.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from api.constants import (
    AGENT_PROPOSAL_APPLIER,
    AGENT_REASONING,
    AGENT_SUSPEND_TTL_SECONDS,
    LEARNING_CONTROL_TTL_SECONDS,
    REDIS_KEY_AGENT_SUSPENDED,
    REDIS_KEY_SIGNAL_WEIGHT_SCALE,
    REDIS_KEY_TRADING_PAUSED,
    REDIS_KEY_TRADING_PAUSED_REASON,
    SIGNAL_WEIGHT_REDUCTION_FACTOR,
    SIGNAL_WEIGHT_SCALE_MIN,
    SOURCE_PROPOSAL_APPLIER,
    STREAM_PROPOSALS,
    FieldName,
    LogType,
    ProposalType,
)
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.agent_heartbeat import write_heartbeat
from api.services.agent_state import AgentStateRegistry
from api.services.agents.base import MultiStreamAgent
from api.services.agents.db_helpers import write_agent_log


class ProposalApplier(MultiStreamAgent):
    """Consume STREAM_PROPOSALS and apply each proposal to the live system."""

    _state_name = AGENT_PROPOSAL_APPLIER

    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        redis_client: Redis,
        *,
        agent_state: AgentStateRegistry | None = None,
    ) -> None:
        super().__init__(
            bus,
            dlq,
            streams=[STREAM_PROPOSALS],
            consumer="proposal-applier",
            agent_state=agent_state,
        )
        self.redis = redis_client
        self._applied_count = 0

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        # Ignore our own log entries in case a downstream consumer ever
        # republishes them — only act on actionable proposal types.
        proposal_type = data.get(FieldName.PROPOSAL_TYPE)
        content = data.get(FieldName.CONTENT) or {}
        action = content.get(FieldName.ACTION) if isinstance(content, dict) else None
        trace_id = data.get(FieldName.TRACE_ID) or f"applier_{uuid.uuid4().hex[:8]}"

        applied: dict[str, Any] | None = None
        try:
            if proposal_type == ProposalType.SIGNAL_WEIGHT_REDUCTION:
                applied = await self._apply_signal_weight_reduction(content)
            elif proposal_type == ProposalType.AGENT_SUSPENSION:
                applied = await self._apply_agent_suspension(content)
            elif proposal_type == ProposalType.AGENT_RETIREMENT:
                applied = await self._apply_trading_pause(content)
            else:
                # parameter_change, code_change, regime_adjustment, new_agent —
                # those need human review; record the proposal but don't auto-apply.
                log_structured(
                    "info",
                    "proposal_skipped_requires_review",
                    proposal_type=proposal_type,
                    trace_id=trace_id,
                )
                return
        except Exception:
            log_structured(
                "error",
                "proposal_apply_failed",
                proposal_type=proposal_type,
                trace_id=trace_id,
                exc_info=True,
            )
            return

        if applied is None:
            return

        self._applied_count += 1
        applied_at = datetime.now(timezone.utc).isoformat()

        log_payload: dict[str, Any] = {
            FieldName.SOURCE: SOURCE_PROPOSAL_APPLIER,
            FieldName.AGENT_NAME: AGENT_PROPOSAL_APPLIER,
            FieldName.PROPOSAL_TYPE: proposal_type,
            FieldName.ACTION: action,
            FieldName.APPLIED: True,
            FieldName.APPLIED_AT: applied_at,
            FieldName.APPLIED_BY: AGENT_PROPOSAL_APPLIER,
            FieldName.TRACE_ID: trace_id,
            FieldName.MESSAGE: applied.get(FieldName.MESSAGE, ""),
            FieldName.PAYLOAD: applied,
        }
        try:
            await write_agent_log(trace_id, LogType.PROPOSAL, log_payload)
        except Exception:
            log_structured(
                "warning",
                "proposal_applier_log_write_failed",
                trace_id=trace_id,
                exc_info=True,
            )

        log_structured(
            "info",
            "proposal_applied",
            proposal_type=proposal_type,
            action=action,
            trace_id=trace_id,
            applied=applied,
        )

        # Heartbeat so the dashboard sees ProposalApplier as alive
        try:
            await write_heartbeat(
                self.redis,
                AGENT_PROPOSAL_APPLIER,
                last_event=f"applied {proposal_type}",
                event_count=self._applied_count,
            )
        except Exception:
            log_structured("warning", "proposal_applier_heartbeat_failed", exc_info=True)

    # ------------------------------------------------------------------
    # Action handlers — each returns a dict describing what changed.
    # ------------------------------------------------------------------

    async def _apply_signal_weight_reduction(self, content: dict[str, Any]) -> dict[str, Any]:
        """Multiply the global signal-weight scale by SIGNAL_WEIGHT_REDUCTION_FACTOR."""
        current_raw = await self.redis.get(REDIS_KEY_SIGNAL_WEIGHT_SCALE)
        try:
            current = float(current_raw) if current_raw is not None else 1.0
        except (TypeError, ValueError):
            current = 1.0
        new_scale = max(current * SIGNAL_WEIGHT_REDUCTION_FACTOR, SIGNAL_WEIGHT_SCALE_MIN)
        await self.redis.set(
            REDIS_KEY_SIGNAL_WEIGHT_SCALE,
            f"{new_scale:.6f}",
            ex=LEARNING_CONTROL_TTL_SECONDS,
        )
        return {
            FieldName.MESSAGE: f"signal_weight_scale {current:.4f} -> {new_scale:.4f}",
            FieldName.WEIGHT_SCALE: round(new_scale, 6),
            "previous_scale": round(current, 6),
            FieldName.REASON: content.get(FieldName.REASON, ""),
        }

    async def _apply_agent_suspension(self, content: dict[str, Any]) -> dict[str, Any]:
        """Mark a specific agent suspended for AGENT_SUSPEND_TTL_SECONDS."""
        agent_name = (
            content.get(FieldName.AGENT_NAME)
            or content.get(FieldName.AGENT)
            or content.get("target_agent")
            or AGENT_REASONING  # default target — the most common culprit
        )
        suspended_until = datetime.now(timezone.utc).timestamp() + AGENT_SUSPEND_TTL_SECONDS
        key = REDIS_KEY_AGENT_SUSPENDED.format(name=agent_name)
        # Write "1" (mirroring the kill_switch contract) so consumers can do
        # the same `== "1"` check, and let TTL drive expiry.  The timestamp
        # is recorded only in the agent_logs payload for human inspection.
        await self.redis.set(key, "1", ex=AGENT_SUSPEND_TTL_SECONDS)
        return {
            FieldName.MESSAGE: f"agent {agent_name} suspended for {AGENT_SUSPEND_TTL_SECONDS}s",
            FieldName.AGENT_NAME: agent_name,
            FieldName.SUSPENDED_UNTIL: suspended_until,
            FieldName.REASON: content.get(FieldName.REASON, ""),
        }

    async def _apply_trading_pause(self, content: dict[str, Any]) -> dict[str, Any]:
        """System-wide trading pause — ExecutionEngine refuses new orders."""
        reason = content.get(FieldName.REASON) or "grade F retirement proposal"
        await self.redis.set(REDIS_KEY_TRADING_PAUSED, "1", ex=LEARNING_CONTROL_TTL_SECONDS)
        await self.redis.set(
            REDIS_KEY_TRADING_PAUSED_REASON, str(reason), ex=LEARNING_CONTROL_TTL_SECONDS
        )
        return {
            FieldName.MESSAGE: f"trading paused: {reason}",
            FieldName.REASON: reason,
        }
