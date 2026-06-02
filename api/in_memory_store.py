from __future__ import annotations

import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from api.config import settings
from api.constants import (
    AGENT_CHALLENGER,
    AGENT_EXECUTION,
    AGENT_GRADE,
    AGENT_IC_UPDATER,
    AGENT_NOTIFICATION,
    AGENT_PROPOSAL_APPLIER,
    AGENT_REASONING,
    AGENT_REFLECTION,
    AGENT_SIGNAL,
    AGENT_STRATEGY_PROPOSER,
    FieldName,
    LogType,
)
from api.services.metrics_calc import win_rate_from_counts
from api.services.notification_summary import compute_notification_summary

DEFAULT_AGENTS: dict[str, dict[str, Any]] = {
    AGENT_SIGNAL: {"status": "idle"},
    AGENT_REASONING: {"status": "idle"},
    AGENT_EXECUTION: {"status": "idle"},
    AGENT_GRADE: {"status": "idle"},
    AGENT_IC_UPDATER: {"status": "idle"},
    AGENT_REFLECTION: {"status": "idle"},
    AGENT_STRATEGY_PROPOSER: {"status": "idle"},
    AGENT_NOTIFICATION: {"status": "idle"},
    AGENT_CHALLENGER: {"status": "idle"},
    AGENT_PROPOSAL_APPLIER: {"status": "idle"},
}
DEFAULT_TRADE_NOTIONAL: float = float(getattr(settings, "EQUITY_PER_TRADE", 1000.0) or 1000.0)
POSITION_EPSILON: float = 1e-9


@dataclass(slots=True)
class InMemoryStore:
    """Best-effort runtime fallback when external dependencies are down."""

    agents: dict[str, dict[str, Any]] = field(default_factory=lambda: deepcopy(DEFAULT_AGENTS))
    notifications: list[dict[str, Any]] = field(default_factory=list)
    grade_history: list[dict[str, Any]] = field(default_factory=list)
    event_history: list[dict[str, Any]] = field(default_factory=list)
    vector_memory: list[dict[str, Any]] = field(default_factory=list)
    agent_runs: list[dict[str, Any]] = field(default_factory=list)
    agent_logs: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    trade_feed: list[dict[str, Any]] = field(default_factory=list)
    last_health: str = "unknown"
    # Learning pipeline collections
    trade_evaluations: list[dict[str, Any]] = field(default_factory=list)
    reflections: list[dict[str, Any]] = field(default_factory=list)
    strategies: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    closed_trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    applied_decision_keys: set[str] = field(default_factory=set)
    rejected_sells: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _has_open_quantity(position: dict[str, Any]) -> bool:
        try:
            qty = float(position.get(FieldName.QTY, 0) or 0)
        except (TypeError, ValueError):
            qty = 0.0
        return abs(qty) > 0

    def _position_unrealized_pnl(self, position: dict[str, Any]) -> float | None:
        """Mark-to-market unrealized PnL for one open position.

        Returns ``None`` when an input needed to compute it is missing/malformed
        so callers can fall back to a stored value or flag the row stale. Uses
        ``abs(qty)`` so a short stored with negative qty still sizes correctly;
        long/short apply side-aware signs. This is the single source of the
        formula shared by every position read path.
        """
        qty = abs(
            self._safe_float(position.get(FieldName.QTY))
            or self._safe_float(position.get(FieldName.QUANTITY))
            or 0.0
        )
        avg_cost = self._safe_float(
            position.get(FieldName.AVG_COST, position.get(FieldName.AVG_ENTRY_PRICE))
        )
        last_price = self._safe_float(
            position.get(FieldName.LAST_PRICE, position.get(FieldName.PRICE))
        )
        if avg_cost is None or last_price is None or qty <= 0:
            return None
        side = str(position.get(FieldName.SIDE) or "").lower()
        if side == "short":
            return round((avg_cost - last_price) * qty, 8)
        return round((last_price - avg_cost) * qty, 8)

    def _normalize_position(self, p: dict[str, Any]) -> dict[str, Any]:
        """Map internal position keys to what the frontend expects.

        The stored unrealized_pnl is written at fill time and goes stale as the
        price moves, so we mark each position to market here (the same formula
        the paired-PnL / equity-curve path uses) and only fall back to the
        stored value when the inputs to compute it are missing.
        """
        qty = self._safe_float(p.get(FieldName.QTY) or p.get(FieldName.QUANTITY)) or 0.0
        current_price = (
            self._safe_float(p.get(FieldName.CURRENT_PRICE))
            or self._safe_float(p.get(FieldName.LAST_PRICE))
            or self._safe_float(p.get(FieldName.PRICE))
            or 0.0
        )
        computed = self._position_unrealized_pnl(p)
        if computed is not None:
            unrealized = computed
        else:
            stored = self._safe_float(p.get(FieldName.UNREALIZED_PNL))
            unrealized = (
                stored if stored is not None else (self._safe_float(p.get(FieldName.PNL)) or 0.0)
            )
        return {
            **p,
            FieldName.QUANTITY: qty,
            FieldName.CURRENT_PRICE: current_price,
            FieldName.UNREALIZED_PNL: unrealized,
            FieldName.PNL: unrealized,
            FieldName.PNL_PERCENT: self._position_pnl_percent(p, unrealized),
        }

    def _position_pnl_percent(
        self, position: dict[str, Any], unrealized: float | None
    ) -> float | None:
        """Percent return on cost basis for one position; ``None`` when not derivable."""
        if unrealized is None:
            return None
        qty = abs(
            self._safe_float(position.get(FieldName.QTY))
            or self._safe_float(position.get(FieldName.QUANTITY))
            or 0.0
        )
        avg_cost = self._safe_float(
            position.get(FieldName.AVG_COST, position.get(FieldName.AVG_ENTRY_PRICE))
        )
        if avg_cost is None or qty <= 0:
            return None
        cost_basis = avg_cost * qty
        if cost_basis == 0:
            return None
        return round(unrealized / cost_basis * 100.0, 4)

    def apply_current_prices(self, prices: dict[str, Any]) -> None:
        """Mark stored open positions to the latest observed prices.

        In memory mode nothing updates a position's ``last_price`` as the market
        moves (it is frozen at fill time), so the dashboard read layer calls this
        with the current Redis price cache to keep every position read path
        marked to market and mutually consistent.
        """
        for symbol, price in prices.items():
            value = self._safe_float(price)
            if value is None:
                continue
            position = self.positions.get(symbol)
            if position is not None:
                position[FieldName.LAST_PRICE] = value
                position[FieldName.CURRENT_PRICE] = value

    def normalized_open_positions(self) -> list[dict[str, Any]]:
        """Frontend-shaped open positions, each marked to market (snapshot view)."""
        return [
            self._normalize_position(p)
            for p in self.positions.values()
            if self._has_open_quantity(p)
        ]

    def upsert_agent(self, agent_id: str, data: dict[str, Any]) -> None:
        existing = self.agents.get(agent_id, {})
        self.agents[agent_id] = {**existing, **data}

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        return self.agents.get(agent_id)

    def add_notification(
        self,
        message: str,
        level: str = "info",
        *,
        notification_type: str = "system",
    ) -> dict[str, Any]:
        payload = {
            FieldName.ID: len(self.notifications) + 1,
            "message": message,
            "type": level,
            "notification_type": notification_type,
            "timestamp": time.time(),
        }
        self.notifications.append(payload)
        return payload

    def record_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Append a full structured notification payload (e.g. trade fill).

        Used as the DB-down fallback for ``NotificationAgent`` so trade
        notifications still hydrate the dashboard via ``/dashboard/state``
        when Postgres is unavailable.
        """
        entry = dict(payload)
        # setdefault keeps an explicit None (memory-cicd #12); coerce a falsy id
        # so the dashboard always has a non-empty id for de-dup / read-tracking.
        if not entry.get(FieldName.ID):
            entry[FieldName.ID] = (
                entry.get(FieldName.NOTIFICATION_ID) or f"mem-{len(self.notifications) + 1}"
            )
        entry.setdefault(FieldName.TIMESTAMP, time.time())
        self.notifications.append(entry)
        if len(self.notifications) > 100:
            self.notifications = self.notifications[-100:]
        return entry

    def add_grade(self, grade_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(grade_payload)
        payload.setdefault(FieldName.TIMESTAMP, time.time())
        # Dedup by trace_id. In memory mode the SAME grade reaches grade_history
        # up to three times: GradeAgent calls both write_agent_log(GRADE) and
        # write_grade_to_db() (each calls add_grade), then the EventPipeline
        # re-adds it from STREAM_AGENT_GRADES. Without dedup the dashboard's
        # learning-events panel shows every grade 2-3x. Merge re-deliveries into
        # the existing row — newest non-null values win (so a genuine re-grade
        # updates the score), while fields only an earlier delivery carried (e.g.
        # self_correction) are preserved. Challenger grades carry no trace_id, so
        # they always append and are never collapsed together.
        trace_id = payload.get(FieldName.TRACE_ID)
        if trace_id:
            for i, existing in enumerate(self.grade_history):
                if existing.get(FieldName.TRACE_ID) == trace_id:
                    merged = {**existing, **{k: v for k, v in payload.items() if v is not None}}
                    self.grade_history[i] = merged
                    return merged
        self.grade_history.append(payload)
        if len(self.grade_history) > 500:
            self.grade_history = self.grade_history[-500:]
        return payload

    def get_grades(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        return list(reversed(self.grade_history[-safe_limit:]))

    def add_event(self, event_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(event_payload)
        payload.setdefault(FieldName.TIMESTAMP, time.time())
        self.event_history.append(payload)
        if len(self.event_history) > 1000:
            self.event_history = self.event_history[-1000:]
        return payload

    def get_events(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        return list(reversed(self.event_history[-safe_limit:]))

    def add_vector_memory(self, memory_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(memory_payload)
        payload.setdefault(FieldName.CREATED_AT, time.time())
        self.vector_memory.append(payload)
        if len(self.vector_memory) > 1000:
            self.vector_memory = self.vector_memory[-1000:]
        return payload

    def add_agent_run(self, run_payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(run_payload)
        payload.setdefault(FieldName.CREATED_AT, time.time())
        self.agent_runs.append(payload)
        if len(self.agent_runs) > 500:
            self.agent_runs = self.agent_runs[-500:]
        return payload

    def add_order(self, order: dict[str, Any]) -> dict[str, Any]:
        payload = dict(order)
        payload.setdefault(FieldName.CREATED_AT, time.time())
        self.orders.append(payload)
        if len(self.orders) > 500:
            self.orders = self.orders[-500:]
        return payload

    def upsert_position(self, symbol: str, position: dict[str, Any]) -> None:
        existing = self.positions.get(symbol, {})
        self.positions[symbol] = {**existing, **position}

    def add_agent_log(self, log_payload: dict[str, Any]) -> dict[str, Any]:
        """Append one row to the in-memory agent_logs list.

        Surfaces reasoning / grade / reflection messages on the dashboard's
        Agent Thought Stream when Postgres is unavailable.
        """
        payload = dict(log_payload)
        payload.setdefault(FieldName.TIMESTAMP, time.time())
        self.agent_logs.append(payload)
        if len(self.agent_logs) > 500:
            self.agent_logs = self.agent_logs[-500:]
        return payload

    def upsert_trade_fill(self, trade: dict[str, Any]) -> dict[str, Any]:
        """Upsert one row into the in-memory trade_feed list.

        Keyed on execution_trace_id so grade/reflection updates merge into the
        existing row instead of creating duplicates.
        """
        payload = dict(trade)
        payload.setdefault(FieldName.CREATED_AT, time.time())
        key = payload.get(FieldName.EXECUTION_TRACE_ID) or payload.get(FieldName.ORDER_ID)
        if key:
            for i, existing in enumerate(self.trade_feed):
                if (
                    existing.get(FieldName.EXECUTION_TRACE_ID) == key
                    or existing.get(FieldName.ORDER_ID) == key
                ):
                    merged = {**existing, **{k: v for k, v in payload.items() if v is not None}}
                    self.trade_feed[i] = merged
                    return merged
        self.trade_feed.append(payload)
        if len(self.trade_feed) > 500:
            self.trade_feed = self.trade_feed[-500:]
        return payload

    # ------------------------------------------------------------------
    # Learning pipeline collections
    # ------------------------------------------------------------------

    def add_trade_evaluation(self, payload: dict[str, Any]) -> dict[str, Any]:
        entry = dict(payload)
        entry.setdefault(FieldName.CREATED_AT, time.time())
        self.trade_evaluations.append(entry)
        if len(self.trade_evaluations) > 500:
            self.trade_evaluations = self.trade_evaluations[-500:]
        return entry

    def get_trade_evaluations(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        return list(reversed(self.trade_evaluations[-safe_limit:]))

    def add_reflection(self, payload: dict[str, Any]) -> dict[str, Any]:
        entry = dict(payload)
        # Coerce a falsy id (setdefault keeps an explicit None — memory-cicd #12).
        if not entry.get(FieldName.ID):
            entry[FieldName.ID] = str(uuid.uuid4())
        entry.setdefault(FieldName.CREATED_AT, time.time())
        self.reflections.append(entry)
        if len(self.reflections) > 100:
            self.reflections = self.reflections[-100:]
        return entry

    def get_reflections(self, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 50))
        return list(reversed(self.reflections[-safe_limit:]))

    def add_strategy(self, payload: dict[str, Any]) -> dict[str, Any]:
        entry = dict(payload)
        # Coerce a falsy id (setdefault keeps an explicit None — memory-cicd #12).
        if not entry.get(FieldName.ID):
            entry[FieldName.ID] = str(uuid.uuid4())
        entry.setdefault(FieldName.CREATED_AT, time.time())
        self.strategies.append(entry)
        if len(self.strategies) > 100:
            self.strategies = self.strategies[-100:]
        return entry

    def get_strategies(self, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 50))
        return list(reversed(self.strategies[-safe_limit:]))

    def dashboard_fallback_snapshot(self) -> dict[str, Any]:
        now = time.time()
        notifications = list(self.notifications[-100:])
        notification_summary = compute_notification_summary(notifications)

        return {
            FieldName.ORDERS: list(reversed(self.orders[-50:])),
            FieldName.POSITIONS: self.normalized_open_positions(),
            FieldName.AGENT_LOGS: list(reversed(self.agent_logs[-50:])),
            FieldName.LEARNING_EVENTS: list(reversed(self.grade_history[-20:])),
            FieldName.PROPOSALS: [
                e
                for e in reversed(self.event_history[-100:])
                if e.get(FieldName.LOG_TYPE) == LogType.PROPOSAL
            ][:20],
            FieldName.TRADE_FEED: list(reversed(self.trade_feed[-50:])),
            FieldName.SIGNALS: [],
            FieldName.RISK_ALERTS: [],
            FieldName.PRICES: {},
            FieldName.IC_WEIGHTS: {},
            FieldName.AGENT_STATUSES: [
                {
                    FieldName.NAME: name,
                    FieldName.STATUS: data.get(FieldName.STATUS, "unknown"),
                    FieldName.LAST_SEEN: data.get(FieldName.LAST_SEEN, now),
                    FieldName.LAST_SEEN_AT: data.get(FieldName.LAST_SEEN_AT),
                    FieldName.LAST_EVENT: data.get(FieldName.LAST_EVENT, ""),
                    FieldName.EVENT_COUNT: int(data.get(FieldName.EVENT_COUNT, 0) or 0),
                    FieldName.SOURCE: data.get(FieldName.SOURCE, "in_memory"),
                    FieldName.SECONDS_AGO: max(
                        0,
                        int(now - (self._safe_float(data.get(FieldName.LAST_SEEN)) or now)),
                    ),
                }
                for name, data in self.agents.items()
            ],
            FieldName.NOTIFICATIONS: notifications,
            FieldName.DECISIONS: list(reversed(self.decisions[-50:])),
            FieldName.CLOSED_TRADES: list(reversed(self.closed_trades[-50:])),
            FieldName.EQUITY_CURVE: list(self.equity_curve[-200:]),
            FieldName.NOTIFICATION_SUMMARY: notification_summary,
            FieldName.MODE: "in_memory",
            FieldName.DB_HEALTH: self.last_health,
            FieldName.PERSISTENCE_MODE: "memory",  # Clear indication of deliberate in-memory mode
            "source": "in_memory",
            FieldName.HAS_DATA: bool(
                self.decisions or self.orders or self.positions or self.notifications
            ),
        }

    def apply_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        decision_key = self._decision_key(payload)
        if decision_key in self.applied_decision_keys:
            return {
                FieldName.ID: payload.get(FieldName.ID)
                or payload.get(FieldName.TRACE_ID)
                or decision_key,
                FieldName.DEDUPLICATED: True,
            }
        self.applied_decision_keys.add(decision_key)
        action = str(payload.get(FieldName.ACTION, "hold")).upper()
        symbol = str(payload.get(FieldName.SYMBOL) or "").strip()
        price = self._safe_float(payload.get(FieldName.PRICE)) or 0.0
        explicit_quantity = self._safe_float(payload.get(FieldName.QTY))
        event = {
            FieldName.ID: payload.get(FieldName.ID)
            or payload.get(FieldName.TRACE_ID)
            or f"mem-dec-{len(self.decisions) + 1}",
            FieldName.TRACE_ID: payload.get(FieldName.TRACE_ID),
            "timestamp": payload.get(FieldName.TIMESTAMP) or datetime.now(timezone.utc).isoformat(),
            FieldName.SYMBOL: symbol,
            FieldName.ACTION: action,
            FieldName.PRICE: price,
            FieldName.QTY: explicit_quantity or 0.0,
            FieldName.CONFIDENCE: self._safe_float(payload.get(FieldName.CONFIDENCE)),
            FieldName.AGENT: payload.get(FieldName.AGENT) or "reasoning_agent",
            FieldName.REASON: payload.get(LogType.REASONING_SUMMARY)
            or payload.get(FieldName.REASON),
        }
        self.decisions.append(event)
        if len(self.decisions) > 500:
            self.decisions = self.decisions[-500:]
        if action not in {"BUY", "SELL"} or not symbol or price <= 0:
            return event
        pos = self.positions.get(
            symbol, {FieldName.SYMBOL: symbol, FieldName.QTY: 0.0, FieldName.AVG_ENTRY_PRICE: 0.0}
        )
        pos_qty = self._safe_float(pos.get(FieldName.QTY)) or 0.0
        avg = self._safe_float(pos.get(FieldName.AVG_ENTRY_PRICE)) or price
        if action == "BUY":
            quantity = explicit_quantity
            if (quantity is None or quantity <= 0) and price > 0:
                quantity = DEFAULT_TRADE_NOTIONAL / price
            if quantity is None or quantity <= 0:
                return event
            event[FieldName.QTY] = quantity
            new_qty = pos_qty + quantity
            new_avg = ((avg * pos_qty) + (price * quantity)) / new_qty if new_qty > 0 else price
            pos.update(
                {
                    FieldName.SIDE: "long",
                    FieldName.QTY: new_qty,
                    FieldName.AVG_ENTRY_PRICE: new_avg,
                    FieldName.UNREALIZED_PNL: 0.0,
                    FieldName.PRICE: price,
                }
            )
            self.positions[symbol] = pos
        else:
            if explicit_quantity is None or explicit_quantity <= 0:
                sell_qty = pos_qty
            else:
                sell_qty = min(pos_qty, explicit_quantity)
            event[FieldName.QTY] = sell_qty
            if sell_qty <= 0:
                return event
            realized = (price - avg) * sell_qty
            remaining = max(pos_qty - sell_qty, 0.0)
            self.closed_trades.append(
                {
                    FieldName.SYMBOL: symbol,
                    "entry_price": avg,
                    "exit_price": price,
                    FieldName.QTY: sell_qty,
                    FieldName.PNL: realized,
                    FieldName.TIMESTAMP: event[FieldName.TIMESTAMP],
                }
            )
            self.orders.append(
                {
                    FieldName.SYMBOL: symbol,
                    FieldName.PNL: realized,
                    "status": "closed",
                    FieldName.CREATED_AT: event[FieldName.TIMESTAMP],
                }
            )
            if remaining <= POSITION_EPSILON:
                self.positions.pop(symbol, None)
            else:
                pos.update(
                    {
                        FieldName.QTY: remaining,
                        FieldName.AVG_ENTRY_PRICE: avg,
                        FieldName.PRICE: price,
                    }
                )
                self.positions[symbol] = pos
        paired = self.paired_pnl_payload()[FieldName.SUMMARY]
        self.equity_curve.append(
            {
                FieldName.TIMESTAMP: event[FieldName.TIMESTAMP],
                FieldName.VALUE: paired[FieldName.TOTAL_PNL],
                FieldName.REALIZED_PNL: paired[FieldName.REALIZED_PNL],
                FieldName.UNREALIZED_PNL: paired[FieldName.UNREALIZED_PNL],
                FieldName.TOTAL_PNL: paired[FieldName.TOTAL_PNL],
            }
        )
        if len(self.equity_curve) > 1000:
            self.equity_curve = self.equity_curve[-1000:]
        return event

    def record_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record advisory decision without mutating portfolio/PNL state.

        Use this for reasoning stream events; portfolio mutation belongs to
        execution/fill handlers only.
        """
        decision_key = self._decision_key(payload)
        if decision_key in self.applied_decision_keys:
            return {
                FieldName.ID: payload.get(FieldName.ID)
                or payload.get(FieldName.TRACE_ID)
                or decision_key,
                FieldName.DEDUPLICATED: True,
            }
        self.applied_decision_keys.add(decision_key)
        action = str(payload.get(FieldName.ACTION, "hold")).upper()
        symbol = str(payload.get(FieldName.SYMBOL) or "").strip()
        price = self._safe_float(payload.get(FieldName.PRICE)) or 0.0
        quantity = self._safe_float(payload.get(FieldName.QTY))
        if (quantity is None or quantity <= 0) and price > 0:
            quantity = DEFAULT_TRADE_NOTIONAL / price
        event = {
            FieldName.ID: payload.get(FieldName.ID)
            or payload.get(FieldName.TRACE_ID)
            or f"mem-dec-{len(self.decisions) + 1}",
            FieldName.TRACE_ID: payload.get(FieldName.TRACE_ID),
            "timestamp": payload.get(FieldName.TIMESTAMP) or datetime.now(timezone.utc).isoformat(),
            FieldName.SYMBOL: symbol,
            FieldName.ACTION: action,
            FieldName.PRICE: price,
            FieldName.QTY: quantity or 0.0,
            FieldName.CONFIDENCE: self._safe_float(payload.get(FieldName.CONFIDENCE)),
            FieldName.AGENT: payload.get(FieldName.AGENT) or "reasoning_agent",
            FieldName.REASON: payload.get(LogType.REASONING_SUMMARY)
            or payload.get(FieldName.REASON),
        }
        self.decisions.append(event)
        if len(self.decisions) > 500:
            self.decisions = self.decisions[-500:]
        return event

    def _decision_key(self, payload: dict[str, Any]) -> str:
        for key in ("redis_stream_id", "stream_id", "id", FieldName.TRACE_ID):
            value = payload.get(key)
            if value:
                return f"{key}:{value}"
        timestamp = payload.get(FieldName.TIMESTAMP) or ""
        symbol = payload.get(FieldName.SYMBOL) or ""
        action = payload.get(FieldName.ACTION) or ""
        price = payload.get(FieldName.PRICE) or ""
        return f"derived:{timestamp}:{symbol}:{action}:{price}"

    def has_open_position(self, symbol: str) -> bool:
        """Return True if there is an open LONG position for *symbol* with qty > 0."""
        pos = self.positions.get(symbol)
        if pos is None:
            return False
        side = str(pos.get(FieldName.SIDE, "")).lower()
        qty = self._safe_float(pos.get(FieldName.QTY)) or 0.0
        return side == "long" and qty > 0

    def get_open_position(self, symbol: str) -> dict[str, Any] | None:
        """Return the open position dict for *symbol*, or None if flat/absent."""
        if not self.has_open_position(symbol):
            return None
        return dict(self.positions[symbol])

    def reject_sell_no_position(
        self,
        symbol: str,
        trace_id: str,
        event_id: str,
        reason: str = "NO_OPEN_POSITION",
    ) -> dict[str, Any]:
        """Record a rejected SELL attempt and return the rejection record."""
        entry = {
            FieldName.SYMBOL: symbol,
            FieldName.SIDE: "sell",
            FieldName.REJECTION_REASON: reason,
            FieldName.TRACE_ID: trace_id,
            FieldName.ID: event_id,
            FieldName.TIMESTAMP: time.time(),
        }
        self.rejected_sells.append(entry)
        if len(self.rejected_sells) > 500:
            self.rejected_sells = self.rejected_sells[-500:]
        return entry

    def open_positions(self) -> list[dict[str, Any]]:
        """Return in-memory open positions (long/short, non-zero qty), marked to market.

        Each row's unrealized_pnl/pnl is recomputed from avg_cost vs last_price
        so every position read path agrees with the paired-PnL / equity-curve
        figures instead of returning the stale value stored at fill time.
        """
        rows: list[dict[str, Any]] = []
        for position in self.positions.values():
            side = str(position.get(FieldName.SIDE, "")).lower()
            qty = self._safe_float(position.get(FieldName.QTY))
            if side not in {"long", "short"} or qty is None or abs(qty) <= 0:
                continue
            row = dict(position)
            computed = self._position_unrealized_pnl(row)
            if computed is not None:
                row[FieldName.UNREALIZED_PNL] = computed
                row[FieldName.PNL] = computed
                row[FieldName.PNL_PERCENT] = self._position_pnl_percent(row, computed)
            rows.append(row)
        return rows

    def paired_pnl_payload(self) -> dict[str, Any]:
        """Compute paired PnL payload shape used by REST/WS in-memory fallbacks."""
        closed_trades = list(self.orders[-100:])
        open_positions: list[dict[str, Any]] = []

        realized_pnl = sum(
            self._safe_float(order.get(FieldName.PNL)) or 0.0 for order in closed_trades
        )
        winning_trades = sum(
            1 for order in closed_trades if (self._safe_float(order.get(FieldName.PNL)) or 0.0) > 0
        )
        losing_trades = sum(
            1 for order in closed_trades if (self._safe_float(order.get(FieldName.PNL)) or 0.0) < 0
        )
        total_trades = winning_trades + losing_trades
        unrealized_pnl = 0.0
        for position in self.open_positions():
            row = dict(position)
            existing_unrealized = self._safe_float(row.get(FieldName.UNREALIZED_PNL))
            position_unrealized = self._position_unrealized_pnl(row)
            if position_unrealized is None:
                if existing_unrealized is not None:
                    row[FieldName.UNREALIZED_PNL] = round(existing_unrealized, 8)
                    unrealized_pnl += existing_unrealized
                    open_positions.append(row)
                    continue
                row[FieldName.UNREALIZED_PNL] = None
                row["pnl_stale"] = True
                open_positions.append(row)
                continue
            row[FieldName.UNREALIZED_PNL] = position_unrealized
            unrealized_pnl += position_unrealized
            open_positions.append(row)

        return {
            FieldName.CLOSED_TRADES: closed_trades,
            FieldName.OPEN_POSITIONS: open_positions,
            FieldName.SUMMARY: {
                FieldName.REALIZED_PNL: round(realized_pnl, 8),
                FieldName.UNREALIZED_PNL: round(unrealized_pnl, 8),
                FieldName.TOTAL_PNL: round(realized_pnl + unrealized_pnl, 8),
                FieldName.CLOSED_TRADES: total_trades,
                FieldName.WINNING_TRADES: winning_trades,
                FieldName.WIN_RATE_PERCENT: round(
                    win_rate_from_counts(winning_trades, losing_trades) * 100.0, 2
                ),
                FieldName.OPEN_POSITIONS: len(open_positions),
            },
        }
