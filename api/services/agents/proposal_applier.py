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

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from api.config import settings
from api.constants import (
    AGENT_PROPOSAL_APPLIER,
    AGENT_REASONING,
    AGENT_SUSPEND_TTL_SECONDS,
    LEARNING_CONTROL_TTL_SECONDS,
    REASONING_NODE,
    REDIS_KEY_AGENT_SUSPENDED,
    REDIS_KEY_SIGNAL_WEIGHT_SCALE,
    REDIS_KEY_TRADING_PAUSED,
    REDIS_KEY_TRADING_PAUSED_REASON,
    SIGNAL_WEIGHT_REDUCTION_FACTOR,
    SIGNAL_WEIGHT_SCALE_MIN,
    SOURCE_PROPOSAL_APPLIER,
    STREAM_GITHUB_PRS,
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
from api.services.gitops_publisher import GitOpsPublisher
from backtest.strategies import STRATEGIES


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
        # Injected at startup so an approved NEW_AGENT can spawn a challenger
        # dynamically (config, no deploy). None → fall back to filing an issue.
        self.spawner: Any = None
        # Elegant dispatch: proposal_type → handler(content, trace_id) -> dict|None.
        # Each handler returns an "applied" summary, or None to skip logging.
        self._handlers: dict[str, Any] = {
            ProposalType.SIGNAL_WEIGHT_REDUCTION: self._apply_signal_weight_reduction,
            ProposalType.AGENT_SUSPENSION: self._apply_agent_suspension,
            ProposalType.AGENT_RETIREMENT: self._apply_trading_pause,
            ProposalType.PARAMETER_CHANGE: self._emit_param_change_artifact,
            ProposalType.PROMPT_EVOLUTION: self._apply_prompt_evolution,
            ProposalType.NEW_AGENT: self._apply_new_agent,
            ProposalType.CODE_CHANGE: self._file_code_change_issue,
            ProposalType.REGIME_ADJUSTMENT: self._file_regime_issue,
        }

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        # Ignore our own log entries in case a downstream consumer ever
        # republishes them — only act on actionable proposal types.
        proposal_type = data.get(FieldName.PROPOSAL_TYPE)
        content = data.get(FieldName.CONTENT) or {}
        action = content.get(FieldName.ACTION) if isinstance(content, dict) else None
        trace_id = data.get(FieldName.TRACE_ID) or f"applier_{uuid.uuid4().hex[:8]}"

        handler = self._handlers.get(proposal_type)
        if handler is None:
            log_structured(
                "info",
                "proposal_skipped_unknown_type",
                proposal_type=proposal_type,
                trace_id=trace_id,
            )
            return

        applied: dict[str, Any] | None = None
        try:
            applied = await handler(content, trace_id)
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

    async def _apply_prompt_evolution(
        self, content: dict[str, Any], trace_id: str
    ) -> dict[str, Any] | None:
        """Promote an LLM-drafted adaptive directive into the prompt store.

        Gated on PROMPT_EVOLUTION_AUTO_APPLY — when off, the proposal is left for
        a manual apply (via the proposals UI) rather than taking effect live. The
        directive is always subordinate to the immutable constitution and fully
        version-historied, so this is safe to automate and reversible.
        """
        if not settings.PROMPT_EVOLUTION_AUTO_APPLY:
            log_structured("info", "prompt_evolution_skipped_manual_apply", trace_id=trace_id)
            return None
        from api.services.prompt_store import get_prompt_store  # noqa: PLC0415

        store = get_prompt_store()
        if store is None:
            log_structured("warning", "prompt_evolution_no_store", trace_id=trace_id)
            return None
        node = content.get(FieldName.NODE) or REASONING_NODE
        text = str(content.get(FieldName.TEXT) or "").strip()
        if not text:
            return None
        record = await store.set_directive(
            node,
            text,
            rationale=str(content.get(FieldName.RATIONALE) or ""),
            source=AGENT_PROPOSAL_APPLIER,
        )
        return {
            FieldName.MESSAGE: f"adaptive directive for {node} → v{record[FieldName.VERSION]}",
            FieldName.NODE: node,
            FieldName.VERSION: record[FieldName.VERSION],
        }

    async def _apply_new_agent(
        self, content: dict[str, Any], trace_id: str
    ) -> dict[str, Any] | None:
        """A NEW_AGENT proposal spawns a shadow challenger DYNAMICALLY when its
        strategy already exists (pure config, no deploy); a brand-new strategy
        needs code, so it falls back to a GitHub issue."""
        config = content.get(FieldName.CHALLENGER_CONFIG) or {}
        strategy = str(config.get(FieldName.STRATEGY) or "")
        if self.spawner is not None and strategy in STRATEGIES:
            descriptor = await self.spawner.spawn(config)
            return {
                FieldName.MESSAGE: f"challenger spawned for strategy '{strategy}'",
                FieldName.PROPOSAL_TYPE: ProposalType.NEW_AGENT,
                **descriptor,
            }
        # No spawner (e.g. tests) or unknown strategy → needs human code work.
        return await self._file_feature_issue(ProposalType.NEW_AGENT, content, trace_id)

    async def _file_code_change_issue(
        self, content: dict[str, Any], trace_id: str
    ) -> dict[str, Any] | None:
        return await self._file_feature_issue(ProposalType.CODE_CHANGE, content, trace_id)

    async def _file_regime_issue(
        self, content: dict[str, Any], trace_id: str
    ) -> dict[str, Any] | None:
        return await self._file_feature_issue(ProposalType.REGIME_ADJUSTMENT, content, trace_id)

    async def _file_feature_issue(
        self, proposal_type: str, content: dict[str, Any], trace_id: str
    ) -> dict[str, Any] | None:
        """File a GitHub issue for a code/feature/tool/agent proposal.

        Best-effort: dry-run no-op when GitOps is unconfigured. Returns an
        applied-summary dict; ``None`` only when the issue could not be opened.
        """
        description = str(
            content.get(FieldName.DESCRIPTION) or content.get(FieldName.REASON) or ""
        ).strip()
        title = f"[auto] {proposal_type}: {description[:80] or 'learning-loop proposal'}"
        body = (
            f"Automated **{proposal_type}** proposal from the learning loop — this "
            f"needs code (a new tool, prompt, agent, or feature), so it is filed as an "
            f"issue rather than edited automatically.\n\n"
            f"- **description**: {description or 'n/a'}\n"
            f"- **trace_id**: `{trace_id}`\n\n"
            f"```json\n{json.dumps(content, indent=2, default=str)[:2000]}\n```"
        )
        result = await GitOpsPublisher().open_feature_issue(
            title, body, labels=["auto-proposal", proposal_type]
        )
        return {
            FieldName.MESSAGE: f"feature issue ({result.get(FieldName.STATUS)}) for {proposal_type}",
            FieldName.PROPOSAL_TYPE: proposal_type,
            FieldName.STATUS: result.get(FieldName.STATUS),
            FieldName.PR_URL: result.get(FieldName.PR_URL),
        }

    async def _apply_signal_weight_reduction(
        self, content: dict[str, Any], trace_id: str = ""
    ) -> dict[str, Any]:
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
            FieldName.PREVIOUS_SCALE: round(current, 6),
            FieldName.REASON: content.get(FieldName.REASON, ""),
        }

    async def _apply_agent_suspension(
        self, content: dict[str, Any], trace_id: str = ""
    ) -> dict[str, Any]:
        """Mark a specific agent suspended for AGENT_SUSPEND_TTL_SECONDS."""
        agent_name = (
            content.get(FieldName.AGENT_NAME)
            or content.get(FieldName.AGENT)
            or content.get(FieldName.TARGET_AGENT)
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

    async def _apply_trading_pause(
        self, content: dict[str, Any], trace_id: str = ""
    ) -> dict[str, Any]:
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

    async def _emit_param_change_artifact(
        self, content: dict[str, Any], trace_id: str
    ) -> dict[str, Any] | None:
        """Turn a PARAMETER_CHANGE proposal into a durable GitOps PR artifact.

        Parameter changes used to be DROPPED here ("requires review"), so the
        learning loop could never tune anything. Instead we publish a structured
        ``pr_request`` to STREAM_GITHUB_PRS for a GitHub Action to consume and open
        a PR editing the value in ``api/constants.py`` — version-controlled and
        human-reviewed. NOTHING is applied to the live system; no capital moves.
        """
        parameter = content.get(FieldName.PARAMETER)
        if not parameter:
            return None
        previous_value = content.get(FieldName.PREVIOUS_VALUE)
        proposed_value = content.get(FieldName.NEW_VALUE)
        reason = content.get(FieldName.REASON, "")
        await self.bus.publish(
            STREAM_GITHUB_PRS,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.TYPE: "pr_request",
                FieldName.SOURCE: SOURCE_PROPOSAL_APPLIER,
                FieldName.PROPOSAL_TYPE: ProposalType.PARAMETER_CHANGE,
                FieldName.PARAMETER: parameter,
                FieldName.PREVIOUS_VALUE: previous_value,
                FieldName.PROPOSED_VALUE: proposed_value,
                FieldName.REASON: reason,
                FieldName.TRACE_ID: trace_id,
                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            },
        )
        # Open a real config-only PR when GitOps auto-PR is configured (token in
        # Render). Best-effort: a dry-run/no-op locally, and any failure leaves
        # the queued artifact intact for the GitHub Action / manual review.
        pr_result = await GitOpsPublisher().open_parameter_pr(
            {
                FieldName.PARAMETER: parameter,
                FieldName.PREVIOUS_VALUE: previous_value,
                FieldName.PROPOSED_VALUE: proposed_value,
                FieldName.REASON: reason,
                FieldName.TRACE_ID: trace_id,
            }
        )
        return {
            FieldName.MESSAGE: (
                f"PR artifact queued for {parameter}: {previous_value} -> {proposed_value}"
            ),
            FieldName.PARAMETER: parameter,
            FieldName.PREVIOUS_VALUE: previous_value,
            FieldName.PROPOSED_VALUE: proposed_value,
            FieldName.STATUS: "pending_pr",
            FieldName.REASON: reason,
            FieldName.PR_URL: pr_result.get(FieldName.PR_URL),
        }
