"""WebSocket broadcaster for a single event pipeline."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from api.constants import (
    AGENT_STALE_THRESHOLD_SECONDS,
    ALL_AGENT_NAMES,
    PIPELINE_STREAMS,
    REDIS_AGENT_STATUS_KEY,
    STREAM_AGENT_LOGS,
    STREAM_EXECUTIONS,
    STREAM_LEARNING_EVENTS,
    STREAM_MARKET_EVENTS,
    STREAM_RISK_ALERTS,
    STREAM_SIGNALS,
    AgentStatus,
    OrderSide,
)
from api.observability import log_structured

_AGENT_NAMES = ALL_AGENT_NAMES

_PIPELINE_STREAMS = PIPELINE_STREAMS
_AGENT_PUSH_INTERVAL = 5  # seconds


class WebSocketBroadcaster:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._running = False
        self._last_error: str | None = None
        self._messages_sent = 0
        self._broadcast_task: asyncio.Task[None] | None = None
        self._redis_client = None
        self._stream_offsets: dict[str, str] = {
            STREAM_SIGNALS: "$",
            STREAM_EXECUTIONS: "$",  # Only actual fills — advisory decisions stay internal
            STREAM_RISK_ALERTS: "$",
            STREAM_LEARNING_EVENTS: "$",
            STREAM_AGENT_LOGS: "$",
        }
        self._idle_sleep_seconds = 0.1
        self._xread_streams_state: str | None = None
        self._agent_push_task: asyncio.Task[None] | None = None

    async def start(self, redis_client=None) -> None:
        if self._running:
            return
        self._running = True
        self._redis_client = redis_client
        self._broadcast_task = asyncio.create_task(
            self._dashboard_broadcast_loop(), name="ws-broadcaster-loop"
        )
        self._agent_push_task = asyncio.create_task(
            self._agent_status_push_loop(), name="ws-agent-push-loop"
        )

    async def stop(self) -> None:
        self._running = False
        for task_attr in ("_broadcast_task", "_agent_push_task"):
            task = getattr(self, task_attr, None)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                setattr(self, task_attr, None)

        for ws in list(self._connections):
            try:
                await ws.close(code=1001)
            except Exception:
                pass
        self._connections.clear()

    async def _dashboard_broadcast_loop(self) -> None:
        while self._running:
            try:
                # Compatibility loop hook (kept intentionally minimal).
                if self._redis_client is not None and hasattr(self._redis_client, "xread"):
                    if not self._stream_offsets:
                        self._last_error = (
                            "No streams registered for websocket broadcaster xread loop"
                        )
                        if self._xread_streams_state != "empty":
                            log_structured("error", "websocket_xread_streams_empty")
                            self._xread_streams_state = "empty"
                        await asyncio.sleep(
                            self._idle_sleep_seconds
                        )  # WebSocket idle sleep - allowed
                        continue

                    if self._xread_streams_state != "ready":
                        log_structured(
                            "debug",
                            "websocket_xread_streams_ready",
                            stream_count=len(self._stream_offsets),
                        )
                        self._xread_streams_state = "ready"

                    messages = await self._redis_client.xread(
                        dict(self._stream_offsets), block=100, count=100
                    )
                    if not messages:
                        await asyncio.sleep(
                            self._idle_sleep_seconds
                        )  # WebSocket idle sleep - allowed
                        continue

                    messages_read = 0
                    broadcasts_attempted = 0
                    for stream_name, stream_messages in messages:
                        if not stream_messages:
                            continue
                        decoded_stream_name = self._decode_redis_value(stream_name)
                        for msg_id, payload in stream_messages:
                            decoded_id = self._decode_redis_value(msg_id)
                            decoded_payload = self._decode_redis_payload(payload)
                            outbound = self._transform_stream_message(
                                decoded_stream_name, decoded_id, decoded_payload
                            )
                            if outbound is None:
                                # Filtered out as noise (hold/reject logs, etc.)
                                messages_read += 1
                                continue
                            await self.broadcast(outbound)
                            messages_read += 1
                            broadcasts_attempted += len(self._connections)

                        *_, (last_id, _payload) = stream_messages
                        self._stream_offsets[decoded_stream_name] = self._decode_redis_value(
                            last_id
                        )

                    log_structured(
                        "debug",
                        "websocket_xread_cycle_processed",
                        streams_returned=len(messages),
                        messages_read=messages_read,
                        broadcasts_attempted=broadcasts_attempted,
                        connected_clients=len(self._connections),
                    )
                else:
                    await asyncio.sleep(self._idle_sleep_seconds)  # WebSocket idle sleep - allowed
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                log_structured("warning", "websocket_background_loop_error", exc_info=True)
                await asyncio.sleep(self._idle_sleep_seconds)  # WebSocket idle sleep - allowed

    async def _agent_status_push_loop(self) -> None:
        """Push agent status + stream metrics to all clients every N seconds.

        This replaces client-side HTTP polling — data arrives via WebSocket
        regardless of page load.
        """
        while self._running:
            try:
                await asyncio.sleep(_AGENT_PUSH_INTERVAL)
                if self._redis_client is None or not self._connections:
                    continue

                now = int(datetime.now(timezone.utc).timestamp())
                agents = []
                for name in _AGENT_NAMES:
                    raw = await self._redis_client.get(REDIS_AGENT_STATUS_KEY.format(name=name))
                    if raw:
                        data = json.loads(raw)
                        last_seen = data.get("last_seen", 0)
                        age = now - last_seen
                        status = (
                            AgentStatus.STALE
                            if age > AGENT_STALE_THRESHOLD_SECONDS
                            else data.get("status", AgentStatus.ACTIVE)
                        )
                        agents.append(
                            {
                                "name": name,
                                "status": status,
                                "event_count": data.get("event_count", 0),
                                "last_event": data.get("last_event", ""),
                                "last_seen": last_seen,
                                "seconds_ago": age,
                            }
                        )
                    else:
                        agents.append(
                            {
                                "name": name,
                                "status": AgentStatus.WAITING,
                                "event_count": 0,
                                "last_event": "",
                                "last_seen": 0,
                                "seconds_ago": 0,
                            }
                        )

                metrics: dict[str, int] = {}
                for stream_name in _PIPELINE_STREAMS:
                    try:
                        metrics[stream_name] = int(await self._redis_client.xlen(stream_name))
                    except Exception:
                        metrics[stream_name] = 0

                await self.broadcast(
                    {
                        "type": "agent_status_update",
                        "agents": agents,
                        "metrics": metrics,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                log_structured("warning", "agent_status_push_loop_error", exc_info=True)

    def _transform_stream_message(
        self, stream: str, msg_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Transform raw Redis stream payloads into frontend-friendly WS messages.

        Filtering rules (dashboard notification feed):
          executions   → type=trade_notification only for BUY/SELL fills (signal: buy/sell side)
          agent_logs   → suppressed entirely (internal verbose logs — not user-facing)
          market_events → type=price_update for the price ticker
          signals      → passthrough with stream tag (pipeline view)
          risk_alerts  → passthrough (important alerts)
          everything else → passthrough with stream tag

        Returns None for events that should be suppressed (not broadcast to clients).
        """
        base = {"stream": stream, "msg_id": msg_id}

        # --- Executions: only surface actual BUY/SELL fills ------------------
        if stream == STREAM_EXECUTIONS:
            event_type = str(payload.get("type", "")).lower()
            side = str(payload.get("side", "")).lower()
            if event_type == "order_filled" and side in (OrderSide.BUY, OrderSide.SELL):
                return {
                    **base,
                    "type": "trade_notification",
                    "symbol": payload.get("symbol"),
                    "side": side,
                    "qty": payload.get("qty"),
                    "fill_price": payload.get("fill_price"),
                    "pnl": payload.get("pnl", 0),
                    "order_id": payload.get("order_id"),
                    "trace_id": payload.get("trace_id"),
                    "filled_at": payload.get("filled_at"),
                    "source": payload.get("source"),
                }
            # Other execution event types (e.g. rejected) are suppressed
            return None

        # --- Agent logs: suppress entirely (too noisy for UI) -----------------
        if stream == STREAM_AGENT_LOGS:
            return None

        # --- Market events: price ticker only (no payload noise) --------------
        if stream == STREAM_MARKET_EVENTS:
            raw_payload = payload.get("payload", payload)
            if isinstance(raw_payload, str):
                try:
                    raw_payload = json.loads(raw_payload)
                except (json.JSONDecodeError, TypeError):
                    raw_payload = payload
            if isinstance(raw_payload, dict) and raw_payload.get("symbol"):
                return {
                    **base,
                    "type": "price_update",
                    "symbol": raw_payload.get("symbol"),
                    "price": raw_payload.get("price"),
                    "change": raw_payload.get("change", 0),
                    "pct": raw_payload.get("pct", 0),
                    "ts": raw_payload.get("ts"),
                    "trace_id": raw_payload.get("trace_id"),
                    "timestamp": payload.get("timestamp"),
                }
            return None

        return {**base, **payload}

    @staticmethod
    def _decode_redis_value(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    @classmethod
    def _decode_redis_payload(cls, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"payload": payload}

        decoded_payload: dict[str, Any] = {}
        for key, value in payload.items():
            decoded_key = cls._decode_redis_value(key)
            decoded_value: Any = value
            if isinstance(value, bytes):
                decoded_value = value.decode("utf-8")
            decoded_payload[decoded_key] = decoded_value
        return decoded_payload

    def register_stream(self, stream_name: str, last_id: str = "$", overwrite: bool = True) -> None:
        stream = stream_name.strip()
        if not stream:
            return
        if overwrite or stream not in self._stream_offsets:
            self._stream_offsets[stream] = last_id

    @property
    def active_connections(self) -> int:
        return len(self._connections)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def messages_sent(self) -> int:
        return self._messages_sent

    async def add_connection(self, websocket: WebSocket) -> None:
        self._connections.add(websocket)
        log_structured(
            "info",
            "ws_client_connected",
            event_name="ws_client_connected",
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
            active_connections=self.active_connections,
        )

    async def remove_connection(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)
        log_structured(
            "info",
            "ws_client_disconnected",
            event_name="ws_client_disconnected",
            msg_id="none",
            event_type="system",
            timestamp=datetime.now(timezone.utc).isoformat(),
            active_connections=self.active_connections,
        )

    async def broadcast(self, data: dict[str, Any]) -> None:
        msg_id = str(data.get("msg_id", "none"))
        event_type = str(data.get("event_type", data.get("type", "unknown")))
        ts = str(data.get("timestamp", datetime.now(timezone.utc).isoformat()))

        disconnected: list[WebSocket] = []
        for websocket in self._connections:
            try:
                await websocket.send_json(data)
                self._messages_sent += 1
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                disconnected.append(websocket)
                log_structured(
                    "error",
                    "ws_client_send_failed",
                    event_name="ws_client_send_failed",
                    msg_id=msg_id,
                    event_type=event_type,
                    timestamp=ts,
                    exc_info=True,
                )

        for ws in disconnected:
            await self.remove_connection(ws)

        log_structured(
            "info",
            "websocket_broadcast",
            event_name="websocket_broadcast",
            msg_id=msg_id,
            event_type=event_type,
            timestamp=ts,
            active_connections=self.active_connections,
            messages_sent=self._messages_sent,
        )


_broadcaster: WebSocketBroadcaster | None = None


def get_broadcaster() -> WebSocketBroadcaster:
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = WebSocketBroadcaster()
    return _broadcaster
