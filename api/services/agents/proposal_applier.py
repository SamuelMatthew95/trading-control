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
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from api.config import settings
from api.constants import (
    AGENT_PROPOSAL_APPLIER,
    AGENT_REASONING,
    AGENT_SUSPEND_TTL_SECONDS,
    APPROVAL_GATED_PROPOSAL_TYPES,
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
    ProposalStatus,
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
from api.services.param_evolution import validate_param_change
from api.services.prompt_store import get_prompt_store
from api.services.redis_store import get_redis_store
from api.services.tool_registry import get_tool_registry
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
        # Bounded LRU of already-applied proposal identities (msg_id when
        # present, else type+trace). Stream retries and DLQ replays redeliver
        # the same proposal; re-running a handler duplicates its side effects.
        self._applied_keys: OrderedDict[str, None] = OrderedDict()
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
            ProposalType.TOOL_GOVERNANCE: self._apply_tool_governance,
            ProposalType.CHALLENGER_PROMOTION: self._apply_challenger_promotion,
        }

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        # Ignore our own log entries in case a downstream consumer ever
        # republishes them — only act on actionable proposal types.
        proposal_type = data.get(FieldName.PROPOSAL_TYPE)
        content = data.get(FieldName.CONTENT) or {}
        action = content.get(FieldName.ACTION) if isinstance(content, dict) else None
        trace_id = data.get(FieldName.TRACE_ID) or f"applier_{uuid.uuid4().hex[:8]}"

        # Idempotency: stream retries / DLQ replays redeliver the SAME proposal
        # (same msg_id). Re-running a handler re-fires its side effects — a
        # duplicate PR artifact, a duplicate audit row in the review queue —
        # so apply each proposal exactly once.
        if self._already_applied(data, proposal_type, trace_id):
            log_structured(
                "info",
                "proposal_apply_skipped_duplicate",
                proposal_type=proposal_type,
                trace_id=trace_id,
            )
            return

        # Approval-gated types sit in the queue until an operator approves (the
        # approval path republishes them with APPROVED=True) — EXCEPT challenger
        # promotions when CHALLENGER_PROMOTION_AUTO_APPLY is on: shadow evidence
        # already cleared the deterministic bar (min trades + beats baseline),
        # and applying only biases the prompt directive / spawns a shadow — no
        # live orders, no capital — so the loop closes without a manual vote.
        if proposal_type in APPROVAL_GATED_PROPOSAL_TYPES and not data.get(FieldName.APPROVED):
            auto_apply = (
                proposal_type == ProposalType.CHALLENGER_PROMOTION
                and settings.CHALLENGER_PROMOTION_AUTO_APPLY
            )
            if not auto_apply:
                log_structured(
                    "info",
                    "proposal_pending_approval",
                    proposal_type=proposal_type,
                    trace_id=trace_id,
                )
                return
            log_structured(
                "info",
                "challenger_promotion_auto_applied",
                trace_id=trace_id,
            )

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
            # An audit row is a RECORD of an action, not a fresh decision. The
            # review queue defaults a missing status to "pending" and a missing
            # content to {}, which rendered every applied change as a new
            # evidence-less proposal with live Approve/Reject buttons (the
            # queue-spam bug). Stamp the terminal status and carry the applied
            # summary so readers show what happened instead.
            FieldName.STATUS: ProposalStatus.APPLIED,
            FieldName.CONTENT: applied,
            FieldName.REQUIRES_APPROVAL: False,
            FieldName.MSG_ID: str(uuid.uuid4()),
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

        # Surface every application in the dashboard notification feed — an
        # auto-applied proposal the operator never voted on must still be
        # impossible to miss. Best-effort: a missing store never blocks the loop.
        notif_store = get_redis_store()
        if notif_store is not None:
            try:
                await notif_store.push_notification(
                    {
                        FieldName.SEVERITY: "info",
                        FieldName.TITLE: f"Proposal applied: {proposal_type}",
                        FieldName.MESSAGE: applied.get(FieldName.MESSAGE, ""),
                        FieldName.NOTIFICATION_TYPE: "proposal.applied",
                        FieldName.TRACE_ID: trace_id,
                        FieldName.TIMESTAMP: applied_at,
                    }
                )
            except Exception:
                log_structured(
                    "warning",
                    "proposal_applier_notification_failed",
                    trace_id=trace_id,
                    exc_info=True,
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

    def _already_applied(self, data: dict[str, Any], proposal_type: Any, trace_id: str) -> bool:
        """True when this proposal identity was already applied (records it if not).

        Approval republishes carry APPROVED=True and must be allowed through
        even when the original (gated, skipped) publish was seen — the key
        includes the approved flag so the operator's approval still acts.
        """
        identity = data.get(FieldName.MSG_ID) or f"{proposal_type}:{trace_id}"
        key = f"{identity}|approved={bool(data.get(FieldName.APPROVED))}"
        if key in self._applied_keys:
            return True
        self._applied_keys[key] = None
        while len(self._applied_keys) > 1000:
            self._applied_keys.popitem(last=False)
        return False

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
        # Say exactly what artifact exists now — "feature issue (dry_run)" read
        # like success while no issue existed anywhere.
        status = result.get(FieldName.STATUS)
        if status == "opened":
            message = f"GitHub issue opened for {proposal_type}: {result.get(FieldName.PR_URL)}"
        elif status == "dry_run":
            message = (
                f"GitHub issue NOT opened for {proposal_type} — GitOps not configured "
                "(set GITHUB_TOKEN / GITHUB_REPO / GITHUB_AUTOPR_ENABLED); proposal recorded only"
            )
        else:
            message = (
                f"GitHub issue failed for {proposal_type} "
                f"({result.get(FieldName.REASON) or status})"
            )
        return {
            FieldName.MESSAGE: message,
            FieldName.PROPOSAL_TYPE: proposal_type,
            FieldName.STATUS: status,
            FieldName.PR_URL: result.get(FieldName.PR_URL),
        }

    async def _apply_tool_governance(
        self, content: dict[str, Any], trace_id: str = ""
    ) -> dict[str, Any] | None:
        """Disable the tools a TOOL_GOVERNANCE proposal flagged for removal.

        Closes the dead-tool loop: GradeAgent flags a negative-alpha or unreliable
        tool, this handler disables it in the in-process registry, and the next
        reasoning prompt stops paying for it. Only ``disable`` suggestions are
        actioned (``review`` is advisory). Returns None when nothing changed so no
        misleading "applied" log is emitted."""
        suggestions = content.get(FieldName.SUGGESTIONS) or []
        registry = get_tool_registry()
        disabled: list[str] = []
        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                continue
            if suggestion.get(FieldName.ACTION) != "disable":
                continue
            name = suggestion.get(FieldName.TOOL)
            if name and registry.set_enabled(name, False):
                disabled.append(name)
        if not disabled:
            return None
        return {
            FieldName.MESSAGE: f"disabled {len(disabled)} tool(s): {', '.join(disabled)}",
            FieldName.TOOLS: disabled,
            FieldName.REASON: content.get(FieldName.REASON, ""),
        }

    async def _apply_challenger_promotion(
        self, content: dict[str, Any], trace_id: str
    ) -> dict[str, Any] | None:
        """Apply an APPROVED challenger promotion — both halves of the loop.

        1. *Advise agent behavior* (durable, visible): append a promotion advisory
           to the adaptive directive via ``PromptStore`` — the same Redis-backed,
           versioned, history-capped channel ``PROMPT_EVOLUTION`` uses. It survives
           restarts/deploys (Redis is external, no TTL), the ReasoningAgent already
           reads it at prompt-assembly, and it renders in the Prompt Evolution
           panel. No new hidden state.
        2. *Promote to a live candidate*: spawn the strategy as a shadow
           ChallengerAgent via the injected spawner (pure config, no deploy) when
           its strategy exists in ``backtest.strategies.STRATEGIES`` — visible in
           the Challengers panel.

        Only reached after the approval path republishes with ``APPROVED=True`` —
        a human always gates this; nothing auto-promotes. Re-approving the same
        promotion is idempotent (the advisory de-dupes).

        ALWAYS returns an applied-summary for a well-formed proposal — even when
        every half was skipped — so an operator approval can never silently
        vanish: the record says exactly what happened and why (the old code
        returned ``None`` here, leaving "Approved" with no trace).
        """
        strategy = str(content.get(FieldName.STRATEGY) or "")
        if not strategy:
            log_structured("warning", "challenger_promotion_missing_strategy", trace_id=trace_id)
            return None  # malformed payload — an "applied" record would be a lie
        edge = content.get(FieldName.SHADOW_EDGE)
        confidence = content.get(FieldName.CONFIDENCE)
        advisory = (
            f"Promoted strategy '{strategy}': favor {strategy}-aligned setups "
            f"(beat baseline by edge {edge}, shadow win-rate {confidence})."
        )
        store_present = get_prompt_store() is not None
        directive = await self._bias_directive_toward(strategy, advisory)
        if directive is not None:
            directive_status = f"directive biased (v{directive[FieldName.VERSION]})"
        elif store_present:
            directive_status = "directive already biased (idempotent re-approval)"
        else:
            directive_status = "directive skipped — no prompt store installed"

        spawned: dict[str, Any] = {}
        config = content.get(FieldName.CHALLENGER_CONFIG) or {FieldName.STRATEGY: strategy}
        if self.spawner is None:
            spawn_status = "spawn skipped — challenger spawner unavailable"
        elif strategy not in STRATEGIES:
            spawn_status = f"spawn skipped — strategy '{strategy}' not in backtest.strategies"
        else:
            spawned = await self.spawner.spawn(config)
            spawn_status = "candidate spawned"

        result: dict[str, Any] = {
            FieldName.MESSAGE: (
                f"challenger '{strategy}' promotion applied: {directive_status}; {spawn_status}"
            ),
            FieldName.PROPOSAL_TYPE: ProposalType.CHALLENGER_PROMOTION,
            FieldName.STRATEGY: strategy,
            FieldName.ADVISORY: advisory,
            FieldName.SHADOW_EDGE: edge,
            **spawned,
        }
        if directive is not None:
            result[FieldName.VERSION] = directive[FieldName.VERSION]
        return result

    async def _bias_directive_toward(self, strategy: str, advisory: str) -> dict[str, Any] | None:
        """Append *advisory* to the durable adaptive directive (idempotent).

        Reuses the ``PromptStore`` so the bias is persistent (Redis, no TTL —
        survives restarts/deploys), versioned/auditable, and visible in the Prompt
        Evolution panel. Appends beneath any existing (e.g. LLM-evolved) directive
        rather than replacing it; de-dupes so re-approval is a no-op. Returns the
        new directive record, or ``None`` when no store is installed or the line
        is already present."""
        store = get_prompt_store()
        if store is None:
            log_structured("warning", "challenger_promotion_no_prompt_store", strategy=strategy)
            return None
        current = await store.get_active_text(REASONING_NODE) or ""
        if advisory in current:
            return None  # already biased toward this strategy — idempotent
        new_text = f"{current}\n{advisory}".strip() if current else advisory
        return await store.set_directive(
            REASONING_NODE,
            new_text,
            rationale=f"operator-approved challenger promotion: {strategy}",
            source=AGENT_PROPOSAL_APPLIER,
        )

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
        # Safe-bounds gate (param_evolution contract: enforced BEFORE emitting a
        # pr_request artifact). An off-allowlist or out-of-bounds change emits
        # nothing — no artifact, no PR, no "applied" audit row — so the queue
        # can never claim the loop acted on an unsafe change.
        validation_error = validate_param_change(str(parameter), proposed_value)
        if validation_error is not None:
            log_structured(
                "warning",
                "param_change_rejected_unsafe",
                parameter=parameter,
                reason=validation_error,
                trace_id=trace_id,
            )
            return None
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
        # The applied record names the real artifact: an OPEN PR with its URL,
        # or the queued stream artifact plus exactly why no PR exists yet.
        pr_status = pr_result.get(FieldName.STATUS)
        change = f"{parameter}: {previous_value} -> {proposed_value}"
        if pr_status == "opened":
            message = f"config PR opened for {change} ({pr_result.get(FieldName.PR_URL)})"
        elif pr_status == "dry_run":
            message = (
                f"PR artifact queued for {change}; auto-PR dry-run — GitOps not configured "
                "(set GITHUB_TOKEN / GITHUB_REPO / GITHUB_AUTOPR_ENABLED)"
            )
        else:
            message = (
                f"PR artifact queued for {change}; auto-PR failed "
                f"({pr_result.get(FieldName.REASON) or pr_status}) — left for the GitHub Action"
            )
        return {
            FieldName.MESSAGE: message,
            FieldName.PARAMETER: parameter,
            FieldName.PREVIOUS_VALUE: previous_value,
            FieldName.PROPOSED_VALUE: proposed_value,
            FieldName.STATUS: "opened" if pr_status == "opened" else "pending_pr",
            FieldName.REASON: reason,
            FieldName.PR_URL: pr_result.get(FieldName.PR_URL),
        }
