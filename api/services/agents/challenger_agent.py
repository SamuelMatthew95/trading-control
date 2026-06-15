"""ChallengerAgent — runs parallel shadow-challenger strategies and grades them."""

from __future__ import annotations

import json
import uuid
from collections import deque
from typing import Any

from api.constants import (
    AGENT_CHALLENGER,
    CHALLENGER_MIN_SHADOW_TRADES,
    CHALLENGER_MIN_SHADOW_WIN_RATE,
    STREAM_AGENT_GRADES,
    STREAM_EXECUTIONS,
    STREAM_MARKET_EVENTS,
    STREAM_PROPOSALS,
    STREAM_TRADE_PERFORMANCE,
    FieldName,
    Grade,
)
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.services.agent_state import AgentStateRegistry
from api.services.agents.base import MultiStreamAgent
from api.services.agents.db_helpers import persist_proposal
from api.utils import now_iso

# ---------------------------------------------------------------------------
# ChallengerAgent — parallel experimental agent instance
# ---------------------------------------------------------------------------


class ChallengerAgent(MultiStreamAgent):
    """A parallel, independently-graded agent instance with an experimental config.

    StrategyProposer can propose a ``new_agent`` when reflection surfaces a
    hypothesis that requires a different parameter set to validate.  Once
    approved via the dashboard, the orchestrator spawns a ChallengerAgent
    alongside the existing pipeline agents.

    The challenger:
      - Receives the same ``executions`` and ``trade_performance`` stream events
      - Computes its own grade using its ``challenger_config`` overrides
      - Records results in ``agent_grades`` and ``trade_lifecycle`` under its
        own ``instance_id``, so performance can be compared in the dashboard
      - Retires itself after ``max_fills`` events (default: 20) and publishes
        a final comparison summary to the ``proposals`` stream

    The orchestrator must call ``.start()`` after instantiation and ``.stop()``
    when retiring the instance.
    """

    _state_name = AGENT_CHALLENGER

    DEFAULT_MAX_FILLS = 20

    def __init__(
        self,
        bus: EventBus,
        dlq: DLQManager,
        *,
        challenger_config: dict[str, Any] | None = None,
        max_fills: int = DEFAULT_MAX_FILLS,
        agent_state: AgentStateRegistry | None = None,
    ) -> None:
        self._challenger_id = str(uuid.uuid4())[:8]
        super().__init__(
            bus,
            dlq,
            # STREAM_MARKET_EVENTS (the UNFILTERED price stream from PricePoller)
            # drives the REAL shadow trades, NOT STREAM_SIGNALS: SignalGenerator
            # throttles LOW/noise ticks before publishing signals, so consuming
            # signals would feed the shadow strategy a sparsified series and skew
            # its PnL/win-rate vs the backtest harness (which sees every bar). Safe
            # from stealing because each agent has its OWN fan-out group.
            # executions/trade_performance remain the grading cadence clock.
            streams=[STREAM_MARKET_EVENTS, STREAM_EXECUTIONS, STREAM_TRADE_PERFORMANCE],
            consumer=f"challenger-{self._challenger_id}",
            agent_state=agent_state,
        )
        # Override the base class default (None) so grade/retire payloads carry
        # a stable identifier even when register_agent_instance() never runs
        # (e.g. unit tests, or when start() is bypassed).
        self._instance_id = self._challenger_id
        self._config: dict[str, Any] = challenger_config or {}
        self._max_fills = max_fills
        self._fills = 0
        self._pnl_buffer: deque[float] = deque(maxlen=100)
        self._grade_history: list[dict[str, Any]] = []
        self._lifecycle_registered = False
        # Liveness + flow telemetry for the dashboard. Live fills can stay 0 for
        # hours (pipeline idle / reasoning LLM in fallback), so these prove the
        # challenger is alive on the raw price stream and let the panel show its
        # shadow trades FLOWING rather than three frozen numbers.
        self._last_tick_at: str | None = None
        self._last_shadow_trade_at: str | None = None
        self._ticks_observed = 0
        self._recent_shadow_trades: deque[dict[str, Any]] = deque(maxlen=10)
        # Shadow engines: this challenger's configured strategy AND the baseline,
        # both fed the SAME live signals so we can A/B their real performance on
        # live data and propose promotion only when the challenger beats baseline.
        self._shadow, self._baseline_shadow = self._build_shadow_engines()
        # Latch so a winning challenger emits its promotion proposal exactly once
        # (the shadow path runs on every tick — without this it would flood the
        # proposal queue). Reset implicitly by spawning a fresh challenger.
        self._shadow_proposal_emitted = False

    def _build_shadow_engines(self):
        """Construct (own, baseline) ShadowTradeEngines from the configured strategy.

        Returns (None, None) when no (or an unknown) strategy is configured, so a
        config-less challenger is a safe no-op on signal events.
        """
        strategy_name = str(self._config.get(FieldName.STRATEGY) or "")
        if not strategy_name:
            return None, None
        try:
            from api.services.shadow_trader import ShadowTradeEngine  # noqa: PLC0415
            from backtest.strategies import STRATEGIES  # noqa: PLC0415

            baseline_name = "baseline_momentum"
            if strategy_name not in STRATEGIES:
                return None, None
            own = ShadowTradeEngine(strategy_name, STRATEGIES[strategy_name])
            baseline = (
                ShadowTradeEngine(baseline_name, STRATEGIES[baseline_name])
                if baseline_name in STRATEGIES
                else None
            )
            return own, baseline
        except Exception:
            log_structured("warning", "challenger_shadow_engine_init_failed", exc_info=True)
            return None, None

    async def start(self) -> None:
        """Begin consuming streams AND register at SHADOW immediately.

        Eager registration (rather than waiting for the first fill in
        ``process``) means an auto-spawned shadow challenger appears on the
        lifecycle panel as soon as the app starts, even before any live trade
        flows — which matters when the pipeline is idle.
        """
        await super().start()
        self._ensure_lifecycle_registered()

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        self._ensure_lifecycle_registered()

        # Unfiltered market_events drive the REAL shadow trades: the challenger runs
        # its OWN strategy (and baseline) on EVERY price tick the poller emits — the
        # same series the backtest harness measures — not the throttled signal stream.
        if stream == STREAM_MARKET_EVENTS:
            self._observe_shadow(data)
            # Surface a winning challenger from SHADOW evidence — independent of
            # live fills, which may never arrive when the pipeline is idle.
            await self._maybe_propose_shadow_promotion()
            return

        if stream == STREAM_TRADE_PERFORMANCE:
            self._pnl_buffer.append(float(data.get(FieldName.PNL) or 0.0))
            self._fills += 1

        if (
            self._fills > 0
            and self._fills % max(int(self._config.get(FieldName.GRADE_EVERY, 10)), 1) == 0
        ):
            await self._grade()

        if self._fills >= self._max_fills:
            await self._retire_with_summary()

    def _observe_shadow(self, data: dict[str, Any]) -> None:
        """Run the configured strategy (and baseline) on one market-events price tick.

        This is what makes the challenger's config REAL: it executes the strategy on
        EVERY live tick as shadow trades, instead of grading the baseline's fills like
        every challenger used to. No real capital is touched.

        market_events wraps the tick in a JSON ``payload`` string (PricePoller); parse
        it the same way SignalGenerator does so we read the same unfiltered series.
        """
        if self._shadow is None:
            return
        raw = data.get(FieldName.PAYLOAD)
        if isinstance(raw, str):
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return
        elif isinstance(raw, dict):
            payload = raw
        else:
            payload = data

        symbol = payload.get(FieldName.SYMBOL)
        try:
            price = float(payload.get(FieldName.PRICE) or 0.0)
        except (TypeError, ValueError):
            return
        if not symbol or price <= 0:
            return
        now = now_iso()
        self._last_tick_at = now
        self._ticks_observed += 1
        closed = self._shadow.observe(symbol, price)
        if closed is not None:
            # A shadow round-trip just realized — record it so the dashboard can
            # show the live FLOW of what the strategy actually did, with PnL.
            self._last_shadow_trade_at = now
            self._recent_shadow_trades.appendleft(
                {
                    FieldName.SYMBOL: closed.symbol,
                    FieldName.DIRECTION: closed.direction,
                    FieldName.PNL: round(closed.pnl, 4),
                    FieldName.ENTRY_PRICE: round(closed.entry_price, 4),
                    FieldName.EXIT_PRICE: round(closed.exit_price, 4),
                    FieldName.TIMESTAMP: now,
                }
            )
        if self._baseline_shadow is not None:
            self._baseline_shadow.observe(symbol, price)

    def _shadow_summary(self) -> dict[str, Any]:
        """Own vs baseline shadow performance on live data (empty when no engine).

        These are challenger-report fields (not payload FieldName keys); they ride
        inside the grade / retirement ``metrics`` block for the dashboard.
        """
        if self._shadow is None:
            return {}
        m = self._shadow.metrics
        summary: dict[str, Any] = {
            "shadow_trades": m.trades,
            "shadow_win_rate": round(m.win_rate, 4),
            "shadow_pnl": round(m.realized_pnl, 4),
            "shadow_sharpe": round(m.sharpe, 4),
        }
        if self._baseline_shadow is not None:
            b = self._baseline_shadow.metrics
            summary["baseline_shadow_trades"] = b.trades
            summary["baseline_shadow_win_rate"] = round(b.win_rate, 4)
            summary["baseline_shadow_pnl"] = round(b.realized_pnl, 4)
            summary["beats_baseline_shadow"] = m.realized_pnl > b.realized_pnl
        return summary

    def activity_snapshot(self) -> dict[str, Any]:
        """Full, connected challenger state for the dashboard.

        Bundles the raw shadow performance (``_shadow_summary``) with the context
        an operator needs to read it: how alive it is (last tick / last trade /
        ticks seen), how close it is to a promotion proposal (``min_shadow_trades``
        threshold + whether one already fired), its live self-grade if any, and a
        rolling window of recent shadow round-trips so the trades visibly FLOW
        instead of reading as three frozen numbers. These are challenger-report
        fields, not payload keys — they ride in the dashboard challenger list.
        """
        snap: dict[str, Any] = dict(self._shadow_summary())
        snap["min_shadow_trades"] = CHALLENGER_MIN_SHADOW_TRADES
        snap["min_shadow_win_rate"] = CHALLENGER_MIN_SHADOW_WIN_RATE
        if self._shadow is not None and self._baseline_shadow is not None:
            # The exact unmet promotion criteria, so the dashboard can show WHY
            # a challenger is (not yet) eligible instead of a bare progress bar.
            snap["promotion_blockers"] = self._promotion_blockers(snap)
        snap["shadow_proposal_emitted"] = self._shadow_proposal_emitted
        snap["ticks_observed"] = self._ticks_observed
        snap["last_tick_at"] = self._last_tick_at
        snap["last_shadow_trade_at"] = self._last_shadow_trade_at
        snap["recent_shadow_trades"] = list(self._recent_shadow_trades)
        if self._shadow is not None:
            snap["open_shadow_positions"] = self._shadow.open_position_count
        if self._grade_history:
            # The most recent LIVE self-grade (needs live fills — absent while the
            # pipeline is idle, which the frontend explains rather than hides).
            snap[FieldName.LATEST_GRADE] = self._grade_history[-1]
        return snap

    def _promotion_blockers(self, summary: dict[str, Any]) -> list[str]:
        """Unmet promotion criteria for the current shadow window (empty = eligible).

        Harder than "beats baseline" alone: the challenger's OWN record must be
        objectively good — enough trades, a minimum win rate, positive realized
        PnL, and positive Sharpe — so a strategy that merely lost less than a
        losing baseline can never promote.
        """
        blockers: list[str] = []
        trades = int(summary.get("shadow_trades") or 0)
        if trades < CHALLENGER_MIN_SHADOW_TRADES:
            blockers.append(f"needs {CHALLENGER_MIN_SHADOW_TRADES - trades} more shadow trades")
        win_rate = float(summary.get("shadow_win_rate") or 0.0)
        if win_rate < CHALLENGER_MIN_SHADOW_WIN_RATE:
            blockers.append(
                f"win rate {win_rate:.0%} below the {CHALLENGER_MIN_SHADOW_WIN_RATE:.0%} minimum"
            )
        if float(summary.get("shadow_pnl") or 0.0) <= 0.0:
            blockers.append("shadow PnL not positive")
        if float(summary.get("shadow_sharpe") or 0.0) <= 0.0:
            blockers.append("shadow Sharpe not positive")
        if not summary.get("beats_baseline_shadow"):
            blockers.append("not beating the baseline shadow's PnL")
        return blockers

    async def _maybe_propose_shadow_promotion(self) -> None:
        """Emit a human-approvable promotion proposal when this challenger beats
        baseline on enough SHADOW evidence.

        This is what makes "beats baseline" mean something: previously the verdict
        was computed and displayed, then thrown away because grades/retirement were
        gated on live ``trade_performance`` fills that never arrive while the
        pipeline is idle. Here the winning verdict surfaces as a backtest-backed
        proposal in the learning-loop queue (``requires_approval=True`` — a human
        promotes, never the system). Latched to fire once per challenger.

        Eligibility is the FULL ``_promotion_blockers`` bar — trades, win rate,
        positive PnL, positive Sharpe, and beating baseline — not just any edge.
        """
        if self._shadow_proposal_emitted or self._shadow is None or self._baseline_shadow is None:
            return
        summary = self._shadow_summary()
        if self._promotion_blockers(summary):
            return

        # Latch before publishing so a publish error cannot re-fire on the next tick.
        self._shadow_proposal_emitted = True
        strategy_name = str(self._config.get(FieldName.STRATEGY) or "")
        edge = round(
            float(summary.get("shadow_pnl") or 0.0)
            - float(summary.get("baseline_shadow_pnl") or 0.0),
            4,
        )
        win_rate = float(summary.get("shadow_win_rate") or 0.0)
        trace_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            FieldName.MSG_ID: str(uuid.uuid4()),
            FieldName.SOURCE: f"challenger-{self._challenger_id}",
            FieldName.TYPE: "proposal",
            # Descriptive type (not an auto-routed ProposalType) — it surfaces in
            # the proposal queue for a human to approve; nothing auto-applies it.
            FieldName.PROPOSAL_TYPE: "challenger_promotion",
            FieldName.REQUIRES_APPROVAL: True,
            FieldName.CHALLENGER_ID: self._challenger_id,
            FieldName.INSTANCE_ID: self._instance_id,
            FieldName.CONFIG: self._config,
            FieldName.CONFIDENCE: win_rate,
            FieldName.CONTENT: {
                FieldName.STRATEGY: strategy_name,
                FieldName.SHADOW_EDGE: edge,
                FieldName.CONFIDENCE: win_rate,
                FieldName.REASON: (
                    f"Shadow challenger '{strategy_name}' beats baseline by {edge:+.2f} PnL "
                    f"over {summary.get('shadow_trades')} shadow trades (win {win_rate:.0%})."
                    f"{self._backtest_verdict()}"
                ),
            },
            FieldName.TRACE_ID: trace_id,
            FieldName.TIMESTAMP: now_iso(),
        }
        payload.update(summary)  # carry the shadow_* report fields for the dashboard
        await self.bus.publish(STREAM_PROPOSALS, payload)
        # Persist so the promotion is visible in the dashboard proposal queue.
        # The ProposalApplier returns early on an approval-gated proposal awaiting
        # a vote without persisting it, so a pending promotion never surfaced for
        # the operator to approve.
        await persist_proposal(payload)
        log_structured(
            "info",
            "challenger_shadow_promotion_proposed",
            challenger_id=self._challenger_id,
            strategy=strategy_name,
            shadow_edge=edge,
            shadow_trades=summary.get("shadow_trades"),
        )

    async def _grade(self) -> None:
        """Compute a grade for this challenger window and publish results."""
        recent = list(self._pnl_buffer)[-20:]
        if not recent:
            return
        win_rate = sum(1 for p in recent if p > 0) / len(recent)
        avg_pnl = sum(recent) / len(recent)
        grade_result = {
            FieldName.CHALLENGER_ID: self._challenger_id,
            FieldName.INSTANCE_ID: self._instance_id,
            FieldName.FILLS: self._fills,
            FieldName.WIN_RATE: round(win_rate, 4),
            FieldName.AVG_PNL: round(avg_pnl, 4),
            FieldName.CONFIG: self._config,
            FieldName.TIMESTAMP: now_iso(),
            # Real shadow-strategy evidence (own vs baseline) on live data.
            **self._shadow_summary(),
        }
        self._grade_history.append(grade_result)

        await self.bus.publish(
            STREAM_AGENT_GRADES,
            {
                FieldName.MSG_ID: str(uuid.uuid4()),
                FieldName.TYPE: "challenger_grade",
                FieldName.SOURCE: f"challenger-{self._challenger_id}",
                FieldName.AGENT: "challenger",
                FieldName.GRADE: Grade.B if win_rate >= 0.5 else Grade.C,
                FieldName.SCORE: win_rate,
                FieldName.SCORE_PCT: round(win_rate * 100, 1),
                FieldName.METRICS: grade_result,
                FieldName.TIMESTAMP: grade_result[FieldName.TIMESTAMP],
            },
        )
        log_structured(
            "info",
            "challenger_grade",
            challenger_id=self._challenger_id,
            fills=self._fills,
            win_rate=win_rate,
            avg_pnl=avg_pnl,
        )

    async def _retire_with_summary(self) -> None:
        """Publish a final comparison summary and stop the challenger."""
        total_pnl = sum(self._pnl_buffer)
        win_rate = (
            sum(1 for p in self._pnl_buffer if p > 0) / len(self._pnl_buffer)
            if self._pnl_buffer
            else 0.0
        )
        summary = {
            FieldName.MSG_ID: str(uuid.uuid4()),
            FieldName.TYPE: "challenger_summary",
            FieldName.SOURCE: f"challenger-{self._challenger_id}",
            FieldName.CHALLENGER_ID: self._challenger_id,
            FieldName.INSTANCE_ID: self._instance_id,
            FieldName.TOTAL_FILLS: self._fills,
            FieldName.TOTAL_PNL: round(total_pnl, 4),
            FieldName.WIN_RATE: round(win_rate, 4),
            FieldName.CONFIG: self._config,
            FieldName.GRADE_HISTORY: self._grade_history[-5:],
            FieldName.TIMESTAMP: now_iso(),
            # Real shadow-strategy evidence (own vs baseline) on live data.
            **self._shadow_summary(),
        }
        await self.bus.publish(
            STREAM_PROPOSALS,
            {
                **summary,
                FieldName.PROPOSAL_TYPE: "challenger_result",
                FieldName.REQUIRES_APPROVAL: False,
                FieldName.CONTENT: {
                    FieldName.DESCRIPTION: (
                        f"Challenger {self._challenger_id} completed {self._fills} fills. "
                        f"Win rate: {win_rate:.0%}, Total PnL: {total_pnl:+.2f}."
                        f"{self._backtest_verdict()}"
                    ),
                    FieldName.CONFIDENCE: win_rate,
                },
            },
        )
        log_structured(
            "info",
            "challenger_retired",
            challenger_id=self._challenger_id,
            total_fills=self._fills,
            total_pnl=total_pnl,
            win_rate=win_rate,
        )
        await self.stop()

    def _backtest_verdict(self) -> str:
        """Judge this challenger's configured strategy in the backtest harness.

        Differentiation and merit are decided offline (the same harness the
        dashboard uses), so the retirement summary carries a real promote/retire
        recommendation rather than only a live win rate. Returns "" when no
        strategy is configured or the harness is unavailable.
        """
        strategy_name = str(self._config.get(FieldName.STRATEGY) or "")
        if not strategy_name:
            return ""
        try:
            from backtest.challenger import evaluate_from_stats  # noqa: PLC0415
            from backtest.compare import compare_on_prices  # noqa: PLC0415
            from backtest.data import synthetic_prices  # noqa: PLC0415
            from backtest.strategies import STRATEGIES  # noqa: PLC0415

            baseline = "baseline_momentum"
            if strategy_name not in STRATEGIES or baseline not in STRATEGIES:
                return ""
            prices = synthetic_prices(n=1500, vol_pct=1.5, seed=1)
            stats = compare_on_prices(
                prices,
                {strategy_name: STRATEGIES[strategy_name], baseline: STRATEGIES[baseline]},
            )
            verdict = evaluate_from_stats(stats, baseline=baseline)
            if verdict is None:
                return ""
            return f" Backtest verdict: {verdict.decision.upper()} — {verdict.reason}"
        except Exception:
            log_structured("warning", "challenger_backtest_verdict_failed", exc_info=True)
            return ""

    def _ensure_lifecycle_registered(self) -> None:
        """Register this challenger's strategy in the lifecycle registry once.

        A running challenger is a SHADOW-stage strategy — it consumes the live
        stream and is graded but places no orders — so it shows up on the
        dashboard's Strategy Lifecycle panel. Best-effort; never blocks process.
        """
        if self._lifecycle_registered:
            return
        self._lifecycle_registered = True
        strategy_name = str(self._config.get(FieldName.STRATEGY) or "")
        if not strategy_name:
            return
        try:
            from api.constants import StrategyStatus  # noqa: PLC0415
            from api.services.strategy_registry import get_strategy_registry  # noqa: PLC0415

            registry = get_strategy_registry()
            if registry.find_by_strategy(strategy_name) is not None:
                return  # already in the lifecycle (startup seeder, or another instance)
            version = registry.register({FieldName.STRATEGY: strategy_name})
            registry.transition(version.version_id, StrategyStatus.BACKTESTED)
            registry.transition(version.version_id, StrategyStatus.SHADOW)
        except Exception:
            log_structured("warning", "challenger_lifecycle_register_failed", exc_info=True)
