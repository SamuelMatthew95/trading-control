"""NotificationAgent — classifies, deduplicates, and routes all system events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from api.constants import (
    AGENT_NOTIFICATION,
    NOTIFICATION_DEDUP_TTL_SECONDS,
    NOTIFICATIONS_STREAM_MAXLEN,
    REDIS_KEY_NOTIFICATION_DEDUP,
    SOURCE_NOTIFICATION,
    STREAM_AGENT_GRADES,
    STREAM_AGENT_LOGS,
    STREAM_DECISIONS,
    STREAM_EXECUTIONS,
    STREAM_FACTOR_IC_HISTORY,
    STREAM_MARKET_TICKS,
    STREAM_NOTIFICATIONS,
    STREAM_PROPOSALS,
    STREAM_REFLECTION_OUTPUTS,
    STREAM_RISK_ALERTS,
    STREAM_SIGNALS,
    STREAM_TRADE_PERFORMANCE,
    FieldName,
    Grade,
    OrderSide,
    Severity,
)
from api.database import AsyncSessionFactory
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.observability import log_structured
from api.runtime_state import is_db_available
from api.schema_version import DB_SCHEMA_VERSION
from api.services.agent_heartbeat import write_heartbeat as _write_heartbeat
from api.services.agent_state import AgentStateRegistry
from api.services.agents.base import MultiStreamAgent
from api.services.agents.notification_payloads import (
    build_trade_notification,
)
from api.services.redis_store import get_redis_store as _get_redis_store

# ---------------------------------------------------------------------------
# NotificationAgent — classify and route all system events
# ---------------------------------------------------------------------------

_STREAM_SEVERITY: dict[str, str] = {
    STREAM_RISK_ALERTS: Severity.URGENT,
    STREAM_PROPOSALS: Severity.INFO,
    STREAM_AGENT_GRADES: Severity.INFO,
    STREAM_REFLECTION_OUTPUTS: Severity.INFO,
    STREAM_FACTOR_IC_HISTORY: Severity.INFO,
    STREAM_EXECUTIONS: Severity.INFO,
    STREAM_TRADE_PERFORMANCE: Severity.INFO,
    STREAM_DECISIONS: Severity.INFO,
    STREAM_SIGNALS: Severity.INFO,
    STREAM_MARKET_TICKS: Severity.INFO,
    STREAM_AGENT_LOGS: Severity.INFO,
}


class NotificationAgent(MultiStreamAgent):
    """Observes all output streams, deduplicates events, and persists notifications."""

    _state_name = AGENT_NOTIFICATION

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
            streams=[
                STREAM_MARKET_TICKS,
                STREAM_SIGNALS,
                STREAM_DECISIONS,
                STREAM_EXECUTIONS,
                STREAM_RISK_ALERTS,
                STREAM_AGENT_LOGS,
                STREAM_TRADE_PERFORMANCE,
                STREAM_AGENT_GRADES,
                STREAM_FACTOR_IC_HISTORY,
                STREAM_REFLECTION_OUTPUTS,
                STREAM_PROPOSALS,
            ],
            consumer="notification-agent",
            agent_state=agent_state,
        )
        self.redis = redis_client
        self._dedup_window_secs = NOTIFICATION_DEDUP_TTL_SECONDS
        self._session_pnl: float = 0.0

    # ------------------------------------------------------------------
    # Rich per-stream message builders
    # ------------------------------------------------------------------

    def _msg_trade_performance(self, data: dict[str, Any]) -> str:
        symbol = str(data.get(FieldName.SYMBOL) or "?")
        side = str(data.get(FieldName.SIDE) or "").upper()
        exit_price = float(data.get(FieldName.EXIT_PRICE) or data.get(FieldName.FILL_PRICE) or 0)
        entry_price = float(data.get(FieldName.ENTRY_PRICE) or exit_price)
        pnl = float(data.get(FieldName.PNL) or 0)
        pnl_pct = float(data.get(FieldName.PNL_PERCENT) or 0)

        if pnl == 0.0:
            # Opening fill — no realized PnL yet
            qty = float(data.get(FieldName.QTY) or 0)
            return f"OPENED — {symbol} ({side}) · Price: ${exit_price:,.2f} | Qty: {qty:.4g}"

        sign = "+" if pnl >= 0 else ""
        return (
            f"CLOSED — {symbol} ({side}) · "
            f"Exit: ${exit_price:,.2f} | Entry: ${entry_price:,.2f} · "
            f"Trade PnL: {sign}${pnl:,.2f} ({sign}{pnl_pct:.2f}%) | "
            f"Session: {'+' if self._session_pnl >= 0 else ''}${self._session_pnl:,.2f}"
        )

    def _msg_signal(self, data: dict[str, Any]) -> str:
        symbol = str(data.get(FieldName.SYMBOL) or "?")
        sig_type = str(data.get(FieldName.TYPE) or data.get(FieldName.SIGNAL_TYPE) or "signal")
        price = float(data.get(FieldName.PRICE) or data.get(FieldName.LAST_PRICE) or 0)
        score = float(data.get(FieldName.COMPOSITE_SCORE) or data.get(FieldName.SCORE) or 0)

        parts = [f"SIGNAL — {symbol} | {sig_type}"]
        if price > 0:
            parts.append(f"Price: ${price:,.2f}")
        if score:
            parts.append(f"Score: {score:.1f}")
        return " · ".join(parts)

    def _msg_risk_alert(self, data: dict[str, Any]) -> str:
        symbol = str(data.get(FieldName.SYMBOL) or "?")
        reason = str(data.get(FieldName.REASON) or data.get(FieldName.MESSAGE) or "risk event")
        return f"RISK ALERT — {symbol} · {reason}"

    def _msg_decision(self, data: dict[str, Any]) -> str:
        symbol = str(data.get(FieldName.SYMBOL) or "?")
        action = str(data.get(FieldName.ACTION) or "?").upper()
        score = float(data.get(FieldName.REASONING_SCORE) or 0)
        edge = str(data.get(FieldName.PRIMARY_EDGE) or "")
        rr = float(data.get(FieldName.RR_RATIO) or 0)

        parts = [f"DECISION — {symbol} | {action}"]
        if score:
            parts.append(f"Score: {score:.2f}")
        if edge:
            parts.append(f"Edge: {edge[:40]}")
        if rr:
            parts.append(f"R/R: {rr:.1f}x")
        return " · ".join(parts)

    # User-facing notifications are restricted to actual executed buy/sell
    # fills. Other streams (signals, decisions, grades, reflections, risk
    # alerts, proposals) are still consumed for internal state (e.g. session
    # PnL on STREAM_TRADE_PERFORMANCE), but they do not surface to the
    # dashboard notification panel.
    _PUBLISH_STREAMS: frozenset[str] = frozenset({STREAM_EXECUTIONS})

    async def process(self, stream: str, redis_id: str, data: dict[str, Any]) -> None:
        if stream == STREAM_NOTIFICATIONS:
            return

        # Track cumulative session PnL from closing fills — runs even when the
        # notification itself is suppressed, so session totals stay accurate.
        if stream == STREAM_TRADE_PERFORMANCE:
            pnl_val = float(data.get(FieldName.PNL) or 0.0)
            if pnl_val != 0.0:
                self._session_pnl += pnl_val

        if stream not in self._PUBLISH_STREAMS:
            # Still write heartbeat so the dashboard reflects agent health.
            await self._heartbeat(stream, data)
            return

        event_type = str(
            data.get(FieldName.TYPE) or data.get(FieldName.NOTIFICATION_TYPE) or stream
        )
        if event_type.lower() != "order_filled":
            await self._heartbeat(stream, data, event_type=event_type)
            return

        # Require a valid buy/sell side on the fill before surfacing it.
        side_raw = str(data.get(FieldName.SIDE) or data.get(FieldName.ACTION) or "").strip().lower()
        try:
            OrderSide(side_raw)
        except ValueError:
            log_structured(
                "debug",
                "notification_dropped_invalid_side",
                stream=stream,
                side=side_raw,
            )
            await self._heartbeat(stream, data)
            return

        symbol_key = str(data.get(FieldName.SYMBOL) or data.get(FieldName.ASSET) or "")
        msg_id = str(data.get(FieldName.MSG_ID) or redis_id)
        trace_key = str(data.get(FieldName.TRACE_ID) or msg_id)
        dedup_key = REDIS_KEY_NOTIFICATION_DEDUP.format(
            stream=stream,
            event_type=event_type,
            side=side_raw,
            symbol=symbol_key,
            trace=trace_key,
        )

        if await self.redis.exists(dedup_key):
            return
        await self.redis.setex(dedup_key, self._dedup_window_secs, "1")

        now_iso = datetime.now(timezone.utc).isoformat()
        severity = self._classify_severity(stream, data)
        notification = build_trade_notification(
            data=data,
            side=side_raw,
            stream=stream,
            event_type=event_type,
            observed_msg_id=msg_id,
            severity=severity,
            timestamp=now_iso,
            schema_version=DB_SCHEMA_VERSION,
            source=SOURCE_NOTIFICATION,
        )

        if is_db_available():
            try:
                from api.core.writer.safe_writer import SafeWriter  # noqa: PLC0415

                writer = SafeWriter(AsyncSessionFactory)
                await writer.write_notification(
                    notification[FieldName.MSG_ID], STREAM_NOTIFICATIONS, notification
                )
            except Exception:
                log_structured(
                    "warning", "notification_persist_failed", stream=stream, exc_info=True
                )
                # DB write failed mid-flight — keep the dashboard hydrated by
                # mirroring to the in-memory store as a best-effort fallback.
                from api.runtime_state import get_runtime_store  # noqa: PLC0415

                get_runtime_store().record_notification(notification)
                log_structured(
                    "warning",
                    "notification_persistence_miss_live_only",
                    stream=stream,
                    notification_id=notification.get(FieldName.NOTIFICATION_ID),
                    trace_id=notification.get(FieldName.TRACE_ID),
                )
        else:
            from api.runtime_state import get_runtime_store  # noqa: PLC0415

            get_runtime_store().record_notification(notification)

        await self.bus.publish(
            STREAM_NOTIFICATIONS,
            notification,
            maxlen=NOTIFICATIONS_STREAM_MAXLEN,
        )
        log_structured("debug", "notification_forwarded", stream=stream, severity=severity)

        # Mirror to Redis-backed REST store so /api/notifications surfaces this
        # notification on the next page load (the WebSocket-only path lost
        # everything if the client wasn't connected at the moment of fire).
        await self._mirror_notification_to_redis_store(
            notification, severity=severity, observed_msg_id=msg_id
        )

        await self._heartbeat(stream, data, event_type=event_type)

    @staticmethod
    async def _mirror_notification_to_redis_store(
        notification: dict[str, Any],
        *,
        severity: str,
        observed_msg_id: str,
    ) -> None:
        """Push a copy of the freshly-fired notification into RedisStore.

        Best-effort: a failure here must never crash the agent loop, since the
        primary delivery channel (WS broadcast) has already succeeded by the
        time we get called.
        """
        store = _get_redis_store()
        if store is None:
            return
        try:
            rest_payload = dict(notification)
            # Preserve the canonical notification_id as the REST list `id` so
            # dedup with the WebSocket stream stays consistent.
            rest_payload.setdefault(
                FieldName.ID, notification.get(FieldName.NOTIFICATION_ID) or observed_msg_id
            )
            rest_payload.setdefault(FieldName.SEVERITY, severity)
            await store.push_notification(rest_payload)
        except Exception:
            log_structured("warning", "notification_redis_store_mirror_failed", exc_info=True)

    async def _heartbeat(
        self, stream: str, data: dict[str, Any], *, event_type: str | None = None
    ) -> None:
        """Write a heartbeat so the dashboard shows NOTIFICATION_AGENT as ACTIVE.

        Called both when a notification is published and when an event is
        consumed-but-suppressed, so the agent looks alive either way.
        """
        if event_type is None:
            event_type = str(
                data.get(FieldName.TYPE) or data.get(FieldName.NOTIFICATION_TYPE) or stream
            )
        try:
            await _write_heartbeat(
                self.redis,
                self._state_name,
                f"stream={stream} event_type={event_type}",
                0,
            )
        except Exception:
            log_structured("warning", "notification_heartbeat_failed", exc_info=True)

    def _classify_severity(self, stream: str, data: dict[str, Any]) -> str:
        if explicit := data.get(FieldName.SEVERITY):
            return str(explicit)
        grade = str(data.get(FieldName.GRADE) or "")
        if grade == Grade.F:
            return Severity.CRITICAL
        if grade == Grade.D:
            return Severity.URGENT
        # Negative PnL on a closing fill → warning
        if stream == STREAM_TRADE_PERFORMANCE:
            pnl = float(data.get(FieldName.PNL) or 0.0)
            if pnl < 0:
                return Severity.WARNING
        if stream == STREAM_EXECUTIONS:
            try:
                pnl = float(data.get(FieldName.PNL))
            except (TypeError, ValueError):
                pnl = None
            if pnl is not None and pnl < 0:
                return Severity.WARNING
        return _STREAM_SEVERITY.get(stream, Severity.INFO)
