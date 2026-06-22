"""GradeAgent — real 4-dimension performance scoring and tool-alpha attribution."""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from api.config import settings
from api.constants import (
    AGENT_GRADE,
    LLM_CALL_DELAY_MS,
    LLM_DELAY_ADJUSTMENT_STEP_MS,
    LLM_DELAY_MAX_MS,
    LLM_RATE_LIMIT_GRADE_THRESHOLD,
    PNL_GRADED_AGENTS,
    SOURCE_GRADE,
    STREAM_AGENT_GRADES,
    STREAM_DECISIONS,
    STREAM_EXECUTIONS,
    STREAM_NOTIFICATIONS,
    STREAM_PROPOSALS,
    STREAM_TRADE_COMPLETED,
    STREAM_TRADE_PERFORMANCE,
    TOOL_REPLAY_REGRESSION,
    FieldName,
    Grade,
    LogType,
    OrderSide,
    ProposalType,
    Severity,
)
from api.database import AsyncSessionFactory
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.runtime_state import get_runtime_store, is_db_available
from api.services.agent_heartbeat import write_heartbeat as _write_heartbeat
from api.services.agent_pnl_store import get_agent_pnl_store
from api.services.agent_state import AgentStateRegistry
from api.services.agents.base import MultiStreamAgent, PairedCloseDeduper
from api.services.agents.db_helpers import (
    persist_proposal,
    persist_trade_evaluation,
    write_agent_log,
    write_grade_to_db,
)
from api.services.agents.grade_analytics import (
    build_self_correction,
    is_actionable,
)
from api.services.agents.scoring import (
    GRADE_SEVERITY,
    compute_weighted_score,
    normalize_cost_eff,
    normalize_ic,
    score_to_grade,
    spearman_correlation,
)
from api.services.agents.trade_scorer import (
    score_trade,
)
from api.services.llm_metrics import llm_metrics as _llm_metrics
from api.services.replay_harness import ReplayHarness
from api.services.tool_registry import get_tool_registry

# ---------------------------------------------------------------------------
# GradeAgent — real 4-dimension performance scoring
# ---------------------------------------------------------------------------


class GradeAgent(MultiStreamAgent):
    """Grades agent performance across 4 weighted dimensions every N fills.

    Score = accuracy×0.35 + IC×0.30 + cost_efficiency×0.20 + latency×0.15
    """

    _state_name = AGENT_GRADE

    def __init__(
        self, bus: EventBus, dlq: DLQManager, *, agent_state: AgentStateRegistry | None = None
    ) -> None:
        super().__init__(
            bus,
            dlq,
            streams=[
                STREAM_EXECUTIONS,
                STREAM_TRADE_PERFORMANCE,
                STREAM_TRADE_COMPLETED,
                # Consumed only to learn which tools informed each decision, so a
                # completed trade's realized PnL can be attributed back to those
                # tools (tool grading). No grade cycle is triggered by decisions.
                STREAM_DECISIONS,
            ],
            consumer="grade-agent",
            agent_state=agent_state,
        )
        self._fills = 0
        self._pnl_buffer: deque[float] = deque(maxlen=100)
        self._confidence_buffer: deque[float] = deque(maxlen=100)
        self._consecutive_low_grades = 0
        # Per-trade evaluation buffer for ReflectionAgent to consume
        self._eval_buffer: deque[dict] = deque(maxlen=200)
        # Tracks the rate_limited_count seen at the last delay adjustment so we
        # only ratchet up when *new* 429s appear, not just because old ones are
        # still inside the 5-minute sliding window.
        self._last_rl_count_at_adjustment: int = 0
        # Rolling (composite_score, dimension_vector) history feeding the
        # self-correction analytics — grade anomaly detection + trajectory.
        self._grade_score_history: deque[tuple[float, dict[str, Any]]] = deque(maxlen=50)
        # Edge-trigger latch: alert once when the diagnostic enters a drop/decay
        # state, stay quiet until it recovers (avoids per-cycle notification spam).
        self._self_correction_active: bool = False
        # Last emitted tool-governance suggestion set (";"-joined tool:action).
        # Edge-triggers the tool-governance proposal so an unchanged set is not
        # re-proposed every grading cycle.
        self._last_tool_governance_key: str | None = None
        # trace_id -> tool names used in that decision, captured from the
        # decisions stream. When the matching trade closes we attribute its
        # realized PnL back to these tools so tool alpha is OUTCOME-driven
        # (not just decision-time latency/reliability). Bounded so a long run
        # cannot grow it without limit.
        self._trace_tools: OrderedDict[str, list[str]] = OrderedDict()
        # symbol -> tool names behind the ENTRY decision whose order actually
        # FILLED. A round-trip close carries only the closing decision's trace,
        # so without this the BUY-side tools never received PnL attribution —
        # tool alpha graded only the exit half of every trade. Populated from
        # STREAM_EXECUTIONS buy fills (decision tools are promoted only once
        # the order fills, so gated/rejected decisions can't mis-attribute).
        self._entry_tools: OrderedDict[str, list[str]] = OrderedDict()
        # The same round-trip close arrives on BOTH trade_performance and
        # trade_completed; grade it exactly once or the durable agent PnL
        # store and every fill-cadence counter double-counts.
        self._close_dedup = PairedCloseDeduper()

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream in (STREAM_TRADE_COMPLETED, STREAM_TRADE_PERFORMANCE):
            if self._close_dedup.is_duplicate(data):
                return
            self._pnl_buffer.append(float(data.get(FieldName.PNL) or 0.0))
            self._fills += 1
            await self._score_and_persist_trade(data)
        elif stream == STREAM_EXECUTIONS:
            self._confidence_buffer.append(float(data.get(FieldName.CONFIDENCE) or 0.5))
            self._remember_entry_tools(data)
        elif stream == STREAM_DECISIONS:
            # Cache the tools used so a later trade can be graded against them.
            self._remember_decision_tools(data)
            return  # decisions never trigger a grade cycle

        trigger = max(int(settings.GRADE_EVERY_N_FILLS), 1)
        if self._fills == 0 or self._fills % trigger != 0:
            # Write idle heartbeat so dashboard shows GradeAgent as active even
            # between grading cycles.
            try:
                from api.redis_client import get_redis as _get_redis  # noqa: PLC0415

                _redis = await _get_redis()
                await _write_heartbeat(
                    _redis,
                    self._state_name,
                    f"fill_buffered:{self._fills}/{trigger}",
                    self._fills,
                    extra={FieldName.EXEC_STATUS: "idle:buffering"},
                )
            except Exception:
                log_structured("warning", "grade_idle_heartbeat_failed", exc_info=True)
            return

        await self._compute_and_publish_grade()

    async def _score_and_persist_trade(self, data: dict[str, Any]) -> None:
        """Score one completed trade deterministically and persist the evaluation."""
        evaluation: dict[str, Any] | None = None
        try:
            evaluation = score_trade(data)
            self._eval_buffer.append(evaluation)
            await persist_trade_evaluation(evaluation)
            log_structured(
                "debug",
                "trade_scored",
                trade_id=evaluation.get(FieldName.TRADE_EVAL_ID),
                grade=evaluation.get(FieldName.GRADE),
                overall_score=evaluation.get(FieldName.OVERALL_SCORE),
            )
        except Exception:
            log_structured("warning", "trade_score_failed", exc_info=True)

        # Surface THIS trade's own deterministic grade onto its feed/lifecycle
        # row right now, decoupled from the every-N-fills agent-grade cadence.
        # score_trade() already grades every closed round-trip, but that grade
        # only reached trade_evaluations — the Learning page's "Graded Trade
        # Outcomes" table reads grade/grade_score off the trade row itself, so a
        # low-volume paper system that rarely hits an agent-grade cycle rendered
        # every closed trade "NR". Grade the row by its OWN evaluation here.
        if evaluation is not None:
            await self._grade_trade_row(data, evaluation)

        # Tool grading — attribute this trade's realized PnL back to the tools
        # that informed the decision behind it, closing the loop from outcome to
        # tool alpha. This is what makes suggest_tool_changes (negative-alpha →
        # disable) and the tool-governance proposal driven by real outcomes.
        self._attribute_pnl_to_tools(data)

        # Agent grading — attribute the same realized PnL to the trading agents
        # so agent_performance can grade them on whether they make money (durable
        # in Redis; see api/services/agent_pnl_store.py).
        await self._attribute_pnl_to_agents(data)

    async def _attribute_pnl_to_agents(self, data: dict[str, Any]) -> None:
        """Fold a completed trade's realized PnL into each trading agent's durable
        record. Best-effort: no store installed or a Redis hiccup is a quiet no-op
        (grading just reads "no data")."""
        pnl = data.get(FieldName.PNL)
        if pnl is None:
            return
        store = get_agent_pnl_store()
        if store is None:
            return
        try:
            value = float(pnl)
        except (TypeError, ValueError):
            return
        for agent_name in PNL_GRADED_AGENTS:
            await store.record_trade(agent_name, value)

    def _remember_decision_tools(self, data: dict[str, Any]) -> None:
        """Cache trace_id -> tool names from a decision event (bounded LRU)."""
        trace_id = data.get(FieldName.TRACE_ID)
        if not trace_id:
            return
        tools = data.get(FieldName.TOOLS_USED) or []
        names = [
            t.get(FieldName.NAME) for t in tools if isinstance(t, dict) and t.get(FieldName.NAME)
        ]
        if not names:
            return
        self._trace_tools[trace_id] = names
        self._trace_tools.move_to_end(trace_id)
        while len(self._trace_tools) > 500:  # bound the map on long runs
            self._trace_tools.popitem(last=False)

    def _remember_entry_tools(self, data: dict[str, Any]) -> None:
        """On a BUY fill, promote the decision's cached tools to the symbol's
        entry slot so the eventual round-trip close can credit them (bounded)."""
        if str(data.get(FieldName.SIDE) or "").lower() != OrderSide.BUY:
            return
        symbol = data.get(FieldName.SYMBOL)
        trace_id = data.get(FieldName.TRACE_ID)
        if not symbol or not trace_id:
            return
        names = self._trace_tools.get(trace_id)
        if not names:
            return
        self._entry_tools[str(symbol)] = list(names)
        self._entry_tools.move_to_end(str(symbol))
        while len(self._entry_tools) > 100:  # one slot per held symbol; tiny
            self._entry_tools.popitem(last=False)

    def _attribute_pnl_to_tools(self, data: dict[str, Any]) -> None:
        """Fold a completed trade's realized PnL into the alpha of every tool
        that informed it — BOTH the closing decision's tools (by trace) and the
        entry decision's tools (by symbol). Pops both so one trade attributes
        exactly once per tool.

        Validate the PnL BEFORE popping: an opening fill carries pnl None
        (serialized to "" by the bus), and popping on it would consume the
        cached tool lists so the eventual close finds nothing to attribute.
        """
        try:
            realized_pnl = float(data.get(FieldName.PNL))
        except (TypeError, ValueError):
            return  # no realized PnL on this event — keep the caches for the close
        trace_id = data.get(FieldName.TRACE_ID)
        closing_names = self._trace_tools.pop(trace_id, None) if trace_id else None
        symbol = data.get(FieldName.SYMBOL)
        entry_names = self._entry_tools.pop(str(symbol), None) if symbol else None
        # One credit per tool per trade, even when the same tool informed both
        # the entry and the exit decision.
        names = list(dict.fromkeys((closing_names or []) + (entry_names or [])))
        if not names:
            return
        try:
            registry = get_tool_registry()
            for name in names:
                registry.record_call(name, latency_ms=0.0, success=True, realized_pnl=realized_pnl)
        except Exception:
            log_structured("warning", "tool_pnl_attribution_failed", exc_info=True)

    async def _compute_and_publish_grade(self) -> None:
        trace_id = f"grade_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        lookback_n = int(settings.GRADE_LOOKBACK_N)

        try:
            accuracy = self._win_rate(lookback_n)
            ic = await self._information_coefficient(lookback_n)
            cost_eff = await self._cost_efficiency(lookback_n)
            latency = await self._latency_score()
            llm_health, llm_snap = self._llm_health_score()
        except Exception:
            log_structured("error", "grade_metric_computation_failed", exc_info=True)
            return

        ic_norm = normalize_ic(ic)
        cost_norm = normalize_cost_eff(cost_eff)
        score = compute_weighted_score(
            accuracy,
            ic_norm,
            cost_norm,
            latency,
            w_accuracy=float(settings.GRADE_WEIGHT_ACCURACY),
            w_ic=float(settings.GRADE_WEIGHT_IC),
            w_cost=float(settings.GRADE_WEIGHT_COST),
            w_latency=float(settings.GRADE_WEIGHT_LATENCY),
        )
        grade = score_to_grade(score)

        dimension_vector = {
            FieldName.ACCURACY: round(accuracy, 4),
            FieldName.IC_NORMALIZED: round(ic_norm, 4),
            FieldName.COST_NORMALIZED: round(cost_norm, 4),
            FieldName.LATENCY_SCORE: round(latency, 4),
        }
        self_correction = self._self_correction(score, dimension_vector)

        payload = {
            FieldName.MSG_ID: str(uuid.uuid4()),
            FieldName.TYPE: "agent_grade",
            FieldName.SOURCE: SOURCE_GRADE,
            FieldName.AGENT: AGENT_GRADE,
            FieldName.AGENT_NAME: AGENT_GRADE,
            FieldName.TRACE_ID: trace_id,
            FieldName.GRADE: grade,
            FieldName.SCORE: score,
            FieldName.CONFIDENCE_SCORE: round(score * 100, 2),
            FieldName.REASONING: (
                f"accuracy={accuracy:.3f}, ic={ic:.3f}, cost_eff={cost_eff:.3f}, "
                f"latency={latency:.3f}, llm_health={llm_health:.3f}"
            ),
            FieldName.SCORE_PCT: round(score * 100, 1),
            FieldName.METRICS: {
                FieldName.ACCURACY: round(accuracy, 4),
                FieldName.IC: round(ic, 4),
                FieldName.IC_NORMALIZED: round(ic_norm, 4),
                FieldName.COST_EFFICIENCY: round(cost_eff, 4),
                FieldName.COST_NORMALIZED: round(cost_norm, 4),
                FieldName.LATENCY_SCORE: round(latency, 4),
                # Also carried at the payload top level; duplicated here because
                # write_grade_to_db and the DB grade-history fallback read it
                # FROM metrics — without it the stored record always said None.
                FieldName.FILLS_GRADED: self._fills,
                FieldName.LLM_HEALTH_SCORE: llm_health,
                FieldName.LLM_RATE_LIMITED: llm_snap.get(FieldName.RATE_LIMITED_COUNT, 0),
                FieldName.LLM_TIMEOUT_COUNT: llm_snap.get(FieldName.TIMEOUT_COUNT, 0),
                FieldName.LLM_SUCCESS_RATE_PCT: round(
                    llm_snap.get(FieldName.SUCCESS_RATE_PCT, 100.0), 1
                ),
                FieldName.LLM_EFFECTIVE_DELAY_MS: llm_snap.get(
                    FieldName.EFFECTIVE_DELAY_MS, LLM_CALL_DELAY_MS
                ),
            },
            FieldName.FILLS_GRADED: self._fills,
            FieldName.SELF_CORRECTION: self_correction,
            FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
        }

        await self.bus.publish(STREAM_AGENT_GRADES, payload)
        log_structured(
            "info",
            "grade_computed",
            grade=grade,
            score=score,
            fills=self._fills,
            ic=ic,
            llm_health=llm_health,
            llm_rate_limited=llm_snap.get(FieldName.RATE_LIMITED_COUNT, 0),
        )

        await write_agent_log(trace_id, LogType.GRADE, payload)
        await write_grade_to_db(
            trace_id,
            payload[FieldName.SCORE_PCT],
            payload[FieldName.METRICS],
            self_correction=self_correction,
        )
        await self._take_grade_action(grade, payload)
        await self._emit_self_correction_alert(self_correction, trace_id)
        await self._emit_tool_governance(trace_id)
        await self._adjust_llm_call_rate(llm_snap)
        await self._backfill_grade_to_lifecycle(grade, payload, trace_id)

        # Write heartbeat with last grade score for dashboard display
        try:
            from api.redis_client import get_redis as _get_redis  # noqa: PLC0415

            _redis = await _get_redis()
            await _write_heartbeat(
                _redis,
                self._state_name,
                f"grade={grade} score={payload[FieldName.SCORE_PCT]}",
                self._fills,
                extra={FieldName.LAST_GRADE_SCORE: payload[FieldName.SCORE_PCT]},
            )
        except Exception:
            log_structured("warning", "grade_heartbeat_failed", exc_info=True)

    async def _backfill_grade_to_lifecycle(
        self, grade: str, payload: dict[str, Any], trace_id: str
    ) -> None:
        """Back-fill the latest agent grade onto the most recent ungraded trade.

        The Learning page's "Graded Trade Outcomes" table reads the grade from
        the trade row itself. In DB mode that row lives in ``trade_lifecycle``;
        in memory mode (no Postgres — the deployment's reality) the in-memory
        trade feed is the ONLY trade record, so the grade has to be merged
        there too. Without the memory branch every fill rendered as "NR".
        """
        grade_label = (
            f"Grade {grade}: accuracy={payload[FieldName.METRICS][FieldName.ACCURACY]:.0%} "
            f"IC={payload[FieldName.METRICS][FieldName.IC]:+.3f}"
        )
        if not is_db_available():
            self._backfill_grade_to_memory(grade, payload, trace_id, grade_label)
            return
        try:
            from api.services.agents.db_helpers import upsert_trade_lifecycle  # noqa: PLC0415

            async with AsyncSessionFactory() as _sess:
                row = await _sess.execute(
                    text("""
                        SELECT execution_trace_id FROM trade_lifecycle
                        WHERE status = 'filled' AND grade IS NULL
                        ORDER BY created_at DESC LIMIT 1
                    """)
                )
                latest = row.first()
            if latest and latest[0]:
                await upsert_trade_lifecycle(
                    execution_trace_id=latest[0],
                    symbol="",  # already set — upsert won't overwrite
                    side=OrderSide.BUY,
                    grade_trace_id=trace_id,
                    grade=grade,
                    grade_score=payload[FieldName.SCORE_PCT],
                    grade_label=grade_label,
                    status="graded",
                    graded_at=datetime.now(timezone.utc).isoformat(),
                )
        except Exception:
            log_structured("warning", "grade_lifecycle_update_failed", exc_info=True)

    def _backfill_grade_to_memory(
        self, grade: str, payload: dict[str, Any], trace_id: str, grade_label: str
    ) -> None:
        """Merge the latest grade onto the newest ungraded in-memory trade row.

        Mirrors the DB back-fill: the most recent fill that has not yet been
        graded gets this cycle's agent grade. Keyed on execution_trace_id so
        ``upsert_trade_fill`` merges into the existing row instead of appending
        a duplicate, and the original ``created_at`` is preserved so the feed
        ordering does not jump when a grade lands.
        """
        try:
            store = get_runtime_store()
            target = next(
                (
                    row
                    for row in reversed(store.trade_feed)
                    if not row.get(FieldName.GRADE)
                    and (row.get(FieldName.EXECUTION_TRACE_ID) or row.get(FieldName.ORDER_ID))
                ),
                None,
            )
            if target is None:
                return
            store.upsert_trade_fill(
                {
                    FieldName.EXECUTION_TRACE_ID: target.get(FieldName.EXECUTION_TRACE_ID),
                    FieldName.ORDER_ID: target.get(FieldName.ORDER_ID),
                    FieldName.CREATED_AT: target.get(FieldName.CREATED_AT),
                    FieldName.GRADE: grade,
                    FieldName.GRADE_SCORE: payload[FieldName.SCORE_PCT],
                    FieldName.GRADE_LABEL: grade_label,
                    FieldName.GRADE_TRACE_ID: trace_id,
                    FieldName.GRADED_AT: datetime.now(timezone.utc).isoformat(),
                    FieldName.STATUS: "graded",
                }
            )
        except Exception:
            log_structured("warning", "grade_memory_update_failed", exc_info=True)

    async def _grade_trade_row(self, data: dict[str, Any], evaluation: dict[str, Any]) -> None:
        """Write a closed trade's OWN deterministic grade onto its trade row.

        Keyed on the trade's execution_trace_id / order_id so the merge lands on
        the existing row (memory ``upsert_trade_fill`` / DB ``upsert_trade_lifecycle``)
        rather than appending a duplicate. Only closed round-trips (realized PnL
        present) are graded — the opening leg is graded when the round-trip closes.
        Best-effort: a write hiccup is a quiet no-op, never blocking grading.
        """
        if data.get(FieldName.PNL) is None:
            return  # open leg — graded on the round-trip close
        execution_trace_id = data.get(FieldName.EXECUTION_TRACE_ID) or data.get(FieldName.TRACE_ID)
        order_id = data.get(FieldName.ORDER_ID)
        if not execution_trace_id and not order_id:
            return
        grade = str(evaluation.get(FieldName.GRADE) or "")
        if not grade:
            return
        grade_score = round(float(evaluation.get(FieldName.OVERALL_SCORE) or 0.0) * 100, 1)
        tags = evaluation.get(FieldName.MISTAKES) or evaluation.get(FieldName.STRENGTHS) or []
        detail = str(tags[0]).replace("_", " ") if tags else ""
        grade_label = f"Grade {grade}" + (f" · {detail}" if detail else "")
        graded_at = datetime.now(timezone.utc).isoformat()

        if not is_db_available():
            try:
                get_runtime_store().upsert_trade_fill(
                    {
                        FieldName.EXECUTION_TRACE_ID: execution_trace_id,
                        FieldName.ORDER_ID: order_id,
                        FieldName.GRADE: grade,
                        FieldName.GRADE_SCORE: grade_score,
                        FieldName.GRADE_LABEL: grade_label,
                        FieldName.GRADED_AT: graded_at,
                        FieldName.STATUS: "graded",
                    }
                )
            except Exception:
                log_structured("warning", "trade_grade_memory_update_failed", exc_info=True)
            return
        try:
            from api.services.agents.db_helpers import upsert_trade_lifecycle  # noqa: PLC0415

            await upsert_trade_lifecycle(
                execution_trace_id=str(execution_trace_id or order_id),
                symbol=str(data.get(FieldName.SYMBOL) or ""),
                side=str(data.get(FieldName.SIDE) or OrderSide.BUY),
                order_id=str(order_id) if order_id else None,
                grade=grade,
                grade_score=grade_score,
                grade_label=grade_label,
                status="graded",
                graded_at=graded_at,
            )
        except Exception:
            log_structured("warning", "trade_grade_lifecycle_update_failed", exc_info=True)

    def _self_correction(self, score: float, dimension_vector: dict[str, Any]) -> dict[str, Any]:
        """Build the self-correction diagnostic, then fold this cycle into history.

        The current grade is compared against the *prior* cycles (so it is never
        part of its own baseline); the trajectory uses the full recent window
        including this cycle.
        """
        baseline_scores = [s for s, _ in self._grade_score_history]
        baseline_vectors = [v for _, v in self._grade_score_history]
        recent_scores = [*baseline_scores, score]
        diagnostic = build_self_correction(
            baseline_scores,
            score,
            baseline_vectors,
            dimension_vector,
            recent_scores,
        )
        self._grade_score_history.append((score, dimension_vector))
        return diagnostic

    async def _emit_self_correction_alert(
        self, self_correction: dict[str, Any], trace_id: str
    ) -> None:
        """Edge-triggered alert on a grade drop or decaying trend.

        Fires a single notification when the diagnostic first becomes actionable
        (entering drop/decay) and stays silent until it recovers — no per-cycle
        spam. Surfaces a degrading trajectory *before* the hard D/F gates in
        ``_take_grade_action`` retire the agent. The full diagnostic always
        rides along in the grade payload regardless; this is only the push
        alert. Positive spikes are never paged on.
        """
        if not is_actionable(self_correction):
            # Recovered (or never tripped) — reset so the next entry re-fires.
            self._self_correction_active = False
            return
        if self._self_correction_active:
            # Already alerted for this episode — don't re-page every cycle.
            return
        self._self_correction_active = True
        log_structured(
            "warning",
            "grade_self_correction",
            anomaly=self_correction[FieldName.ANOMALY_DETECTED],
            direction=self_correction[FieldName.DIRECTION],
            z_score=self_correction[FieldName.Z_SCORE],
            trace_id=trace_id,
        )
        await self.bus.publish(
            STREAM_NOTIFICATIONS,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.SOURCE: SOURCE_GRADE,
                FieldName.TYPE: "notification",
                FieldName.SEVERITY: Severity.WARNING,
                FieldName.NOTIFICATION_TYPE: "grade_self_correction",
                FieldName.MESSAGE: self_correction[FieldName.MESSAGE],
                FieldName.PAYLOAD: {
                    FieldName.SELF_CORRECTION: self_correction,
                    FieldName.TRACE_ID: trace_id,
                },
                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _emit_tool_governance(self, trace_id: str) -> None:
        """Turn the ToolRegistry's read-only advice into an actionable proposal.

        The registry already scores each tool's alpha + reliability from live
        reasoning telemetry, but the only consumer was a passive dashboard
        panel — the loop never closed ("it's not automating"). Each grade cycle
        we surface the actionable suggestions (disable / review) as a single
        human-approval proposal + notification, edge-triggered so an unchanged
        set does not re-propose every cycle. The full suggestion list (incl.
        the ``prioritize`` hint) rides along in the proposal content.
        """
        try:
            suggestions = get_tool_registry().suggest_tool_changes()
        except Exception:
            log_structured("warning", "tool_governance_suggest_failed", exc_info=True)
            return

        # 'prioritize' alone is informational; only disable/review are actionable.
        actionable = [s for s in suggestions if s.action in ("disable", "review")]
        if not actionable:
            self._last_tool_governance_key = None
            return

        key = ";".join(f"{s.tool}:{s.action}" for s in actionable)
        if key == self._last_tool_governance_key:
            return  # unchanged set — already proposed this episode
        self._last_tool_governance_key = key

        serialized = [
            {
                FieldName.TOOL: s.tool,
                FieldName.ACTION: s.action,
                FieldName.SEVERITY: s.severity,
                FieldName.REASON: s.reason,
            }
            for s in suggestions
        ]
        # Full per-tool attribution (alpha / failure / usage), ranked, so the
        # proposal shows HOW each tool is performing — the operator can act on a
        # disable, or use the gaps to decide which new tools to add/enable.
        attribution = [
            {
                FieldName.TOOL: t.name,
                FieldName.ALPHA: round(t.alpha_score, 6),
                FieldName.FAILURE_RATE: round(t.failure_rate, 4),
                FieldName.CALL_COUNT: t.call_count,
                FieldName.ENABLED: t.enabled,
            }
            for t in get_tool_registry().attribution()
        ]
        now_iso = datetime.now(timezone.utc).isoformat()
        proposal = {
            FieldName.MSG_ID: str(uuid.uuid4()),
            FieldName.SOURCE: SOURCE_GRADE,
            FieldName.TYPE: "proposal",
            FieldName.PROPOSAL_TYPE: ProposalType.TOOL_GOVERNANCE,
            FieldName.REQUIRES_APPROVAL: True,
            FieldName.CONTENT: {
                FieldName.SUGGESTIONS: serialized,
                FieldName.ATTRIBUTION: attribution,
                FieldName.BACKTEST: self._recent_backtest_evidence(),
                FieldName.REASON: (
                    f"{len(actionable)} tool-governance action(s) from live "
                    "reasoning telemetry (alpha / reliability / usage)"
                ),
            },
            FieldName.TRACE_ID: trace_id,
            FieldName.TIMESTAMP: now_iso,
        }
        await self.bus.publish(STREAM_PROPOSALS, proposal)
        # Persist so the proposal is visible in the dashboard queue. Publishing
        # to the stream alone is invisible to the UI, which reads the persisted
        # store — the ProposalApplier only persists a proposal once it APPLIES
        # it, so a pending human-approval proposal never surfaced.
        await persist_proposal(proposal)
        await self.bus.publish(
            STREAM_NOTIFICATIONS,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.SOURCE: SOURCE_GRADE,
                FieldName.TYPE: "notification",
                FieldName.SEVERITY: Severity.INFO,
                FieldName.NOTIFICATION_TYPE: "tool_governance",
                FieldName.MESSAGE: f"Tool governance suggests: {key}",
                FieldName.TIMESTAMP: now_iso,
            },
        )
        log_structured(
            "info", "tool_governance_proposal_published", suggestions=key, trace_id=trace_id
        )

    def _win_rate(self, lookback_n: int) -> float:
        recent = list(self._pnl_buffer)[-lookback_n:]
        if not recent:
            return 0.5
        return sum(1 for pnl in recent if pnl > 0) / len(recent)

    def _recent_backtest_evidence(self) -> dict[str, Any]:
        """Replay the recent trade buffer through the same ReplayHarness the
        promotion gate uses, so every proposal carries a MEASURED verdict
        (win rate, total PnL, Sharpe, drawdown, false-positive rate) — not just
        an LLM/heuristic guess. Pure; safe to call on each proposal."""
        _replay_t0 = time.monotonic()
        metrics = ReplayHarness().replay(list(self._eval_buffer))
        # Optimization-phase tool telemetry: the proposal backtest replay ran.
        try:
            get_tool_registry().record_call(
                TOOL_REPLAY_REGRESSION,
                latency_ms=(time.monotonic() - _replay_t0) * 1000,
                success=True,
            )
        except Exception:
            log_structured("warning", "replay_tool_telemetry_failed", exc_info=True)
        return metrics.model_dump()

    async def _information_coefficient(self, lookback_n: int) -> float:
        """Spearman correlation between agent confidence and realized returns."""
        if is_db_available():
            try:
                async with AsyncSessionFactory() as session:
                    result = await session.execute(
                        text("""
                            SELECT ar.confidence, tp.pnl
                            FROM agent_runs ar
                            JOIN orders o ON o.trace_id = ar.trace_id
                            JOIN trade_performance tp ON tp.order_id = o.id
                            ORDER BY ar.created_at DESC
                            LIMIT :n
                        """),
                        {FieldName.N: lookback_n},
                    )
                    rows = result.all()
                    if len(rows) >= 3:
                        confs = [float(r[0]) for r in rows if r[0] is not None]
                        pnls = [float(r[1]) for r in rows if r[1] is not None]
                        if len(confs) >= 3:
                            return spearman_correlation(confs, pnls)
            except Exception:
                log_structured("warning", "ic_db_query_failed_using_buffer", exc_info=True)

        confs = list(self._confidence_buffer)[-lookback_n:]
        pnls = list(self._pnl_buffer)[-lookback_n:]
        paired = list(zip(confs, pnls, strict=False))
        if len(paired) < 3:
            return 0.0
        xs, ys = zip(*paired, strict=False)
        return spearman_correlation(list(xs), list(ys))

    async def _cost_efficiency(self, lookback_n: int) -> float:
        """Total PnL divided by total LLM cost for last N fills."""
        if is_db_available():
            try:
                async with AsyncSessionFactory() as session:
                    result = await session.execute(
                        text("""
                            SELECT COALESCE(SUM(cost_usd), 0)
                            FROM (SELECT cost_usd FROM agent_runs ORDER BY created_at DESC LIMIT :n) sub
                        """),
                        {FieldName.N: lookback_n},
                    )
                    total_cost = float(result.scalar() or 0.0)
            except Exception:
                total_cost = 0.0
        else:
            total_cost = 0.0

        total_pnl = sum(list(self._pnl_buffer)[-lookback_n:])
        if total_cost < 0.0001:
            return total_pnl * 0.1
        return total_pnl / total_cost

    async def _latency_score(self) -> float:
        """1 - (p95_latency_ms / timeout_ms). Higher score means lower latency."""
        timeout_ms = float(settings.LLM_TIMEOUT_SECONDS) * 1000.0
        if not is_db_available():
            return 0.8
        try:
            async with AsyncSessionFactory() as session:
                result = await session.execute(
                    text("""
                        SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)
                        FROM agent_runs
                        WHERE latency_ms > 0 AND created_at > NOW() - INTERVAL '7 days'
                    """)
                )
                p95 = result.scalar()
                if p95 is None:
                    return 0.8
                return max(0.0, 1.0 - (float(p95) / timeout_ms))
        except Exception:
            return 0.8

    def _llm_health_score(self) -> tuple[float, dict[str, Any]]:
        """Read live LLM metrics and return (health_score [0,1], snapshot).

        Health degrades with rate limits and timeouts on top of the raw
        success rate, so even a high success_rate is penalised when the
        window contains many blocked calls.
        """
        snap = _llm_metrics.snapshot()
        success_rate = snap.get(FieldName.SUCCESS_RATE_PCT, 100.0) / 100.0
        rate_limited = snap.get(FieldName.RATE_LIMITED_COUNT, 0)
        timeout_count = snap.get(FieldName.TIMEOUT_COUNT, 0)
        penalty = min(1.0, rate_limited * 0.10 + timeout_count * 0.15)
        health = round(max(0.0, success_rate - penalty), 4)
        return health, snap

    async def _adjust_llm_call_rate(self, llm_snap: dict) -> None:
        """Raise the inter-call delay only when new rate-limited calls appear.

        Called every grading cycle. The 5-minute sliding window can keep a
        burst above the threshold for minutes after the burst ends, so we gate
        on whether rate_limited_count has *increased* since the last time we
        adjusted — preventing repeated ratcheting from a single burst.
        """
        rate_limited = llm_snap.get(FieldName.RATE_LIMITED_COUNT, 0)
        if rate_limited < LLM_RATE_LIMIT_GRADE_THRESHOLD:
            # Count dropped below threshold; reset so a future burst can act.
            self._last_rl_count_at_adjustment = 0
            return

        if rate_limited <= self._last_rl_count_at_adjustment:
            return  # no new 429s since last adjustment — window still draining

        current_delay = _llm_metrics.get_call_delay_ms()
        new_delay = min(current_delay + LLM_DELAY_ADJUSTMENT_STEP_MS, LLM_DELAY_MAX_MS)
        self._last_rl_count_at_adjustment = rate_limited
        if new_delay == current_delay:
            return  # already at cap

        _llm_metrics.set_call_delay_ms(new_delay)
        log_structured(
            "info",
            "grade_agent_raised_llm_delay",
            from_ms=current_delay,
            to_ms=new_delay,
            rate_limited_count=rate_limited,
        )
        await self.bus.publish(
            STREAM_PROPOSALS,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.SOURCE: SOURCE_GRADE,
                FieldName.TYPE: "proposal",
                FieldName.PROPOSAL_TYPE: ProposalType.PARAMETER_CHANGE,
                FieldName.CONTENT: {
                    FieldName.PARAMETER: "LLM_CALL_DELAY_MS",
                    FieldName.PREVIOUS_VALUE: current_delay,
                    FieldName.NEW_VALUE: new_delay,
                    FieldName.REASON: (
                        f"GradeAgent detected {rate_limited} rate-limited calls "
                        f"in the last 5-minute window (threshold={LLM_RATE_LIMIT_GRADE_THRESHOLD})"
                    ),
                    FieldName.AUTO_APPLIED: True,
                },
                FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _take_grade_action(self, grade: str, payload: dict[str, Any]) -> None:
        """Publish notifications and proposals based on grade threshold."""
        severity = GRADE_SEVERITY.get(grade)
        if severity:
            await self.bus.publish(
                STREAM_NOTIFICATIONS,
                {
                    FieldName.MSG_ID: str(uuid.uuid4()),
                    FieldName.SOURCE: SOURCE_GRADE,
                    FieldName.TYPE: "notification",
                    FieldName.SEVERITY: severity,
                    FieldName.NOTIFICATION_TYPE: "agent_grade",
                    FieldName.MESSAGE: (
                        f"Agent grade {grade} ({payload[FieldName.SCORE_PCT]}%) — "
                        f"accuracy={payload[FieldName.METRICS][FieldName.ACCURACY]:.1%} "
                        f"IC={payload[FieldName.METRICS][FieldName.IC]:+.3f}"
                    ),
                    FieldName.PAYLOAD: payload,
                    FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                },
            )

        # Statistical-significance gate: never take a capital-affecting action
        # (weight cut / suspend / retire→pause) on a sample too small for the
        # win-rate / IC to mean anything. A few noisy trades must not pause the
        # whole system — that deadlocks the learning loop (paused → no trades →
        # no grades → no recovery). The grade above is still shown; only the
        # destructive automation waits for enough data.
        if self._fills < int(settings.GRADE_ACTION_MIN_FILLS):
            log_structured(
                "info",
                "grade_action_deferred_insufficient_sample",
                grade=grade,
                fills=self._fills,
                min_fills=int(settings.GRADE_ACTION_MIN_FILLS),
            )
            return

        if grade == Grade.C:
            await self.bus.publish(
                STREAM_PROPOSALS,
                {
                    FieldName.MSG_ID: str(uuid.uuid4()),
                    FieldName.SOURCE: SOURCE_GRADE,
                    FieldName.TYPE: "proposal",
                    FieldName.PROPOSAL_TYPE: ProposalType.SIGNAL_WEIGHT_REDUCTION,
                    FieldName.CONTENT: {
                        FieldName.ACTION: "reduce_signal_weight",
                        FieldName.REDUCTION_PCT: 30,
                        FieldName.REASON: f"Grade {grade}: score {payload[FieldName.SCORE_PCT]}%",
                        FieldName.GRADE_PAYLOAD: payload,
                        FieldName.BACKTEST: self._recent_backtest_evidence(),
                    },
                    FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                },
            )
            self._consecutive_low_grades += 1

        elif grade == Grade.D:
            self._consecutive_low_grades += 1
            if self._consecutive_low_grades >= int(settings.RETIRE_AFTER_N_GRADES):
                await self.bus.publish(
                    STREAM_PROPOSALS,
                    {
                        FieldName.MSG_ID: str(uuid.uuid4()),
                        FieldName.SOURCE: SOURCE_GRADE,
                        FieldName.TYPE: "proposal",
                        FieldName.PROPOSAL_TYPE: ProposalType.AGENT_SUSPENSION,
                        FieldName.CONTENT: {
                            FieldName.ACTION: "suspend_from_live_stream",
                            FieldName.CONSECUTIVE_LOW_GRADES: self._consecutive_low_grades,
                            FieldName.REASON: f"{self._consecutive_low_grades} consecutive D grades",
                            FieldName.BACKTEST: self._recent_backtest_evidence(),
                        },
                        FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                    },
                )

        elif grade == Grade.F:
            self._consecutive_low_grades += 1
            await self.bus.publish(
                STREAM_PROPOSALS,
                {
                    FieldName.MSG_ID: str(uuid.uuid4()),
                    FieldName.SOURCE: SOURCE_GRADE,
                    FieldName.TYPE: "proposal",
                    FieldName.PROPOSAL_TYPE: ProposalType.AGENT_RETIREMENT,
                    FieldName.CONTENT: {
                        FieldName.ACTION: "retire_immediately",
                        FieldName.REASON: f"Grade F: score {payload[FieldName.SCORE_PCT]}%",
                        FieldName.BACKTEST: self._recent_backtest_evidence(),
                    },
                    FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                },
            )

        else:
            self._consecutive_low_grades = 0
