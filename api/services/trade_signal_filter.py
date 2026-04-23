"""
Trade Signal Filter - Server-Side Guard middleware.

This middleware implements the "Silent Ingress" that filters out noise
and only allows TRADE_SIGNAL events to trigger database writes and WebSocket emissions.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from api.observability import log_structured


class SignalType(Enum):
    """Enum for signal types that are allowed to pass through."""

    TRADE_SIGNAL = "TRADE_SIGNAL"
    AGENT_LOG = "agent_log"
    INFO = "info"
    DEBUG = "debug"
    HOLD = "hold"
    SYSTEM = "system"


class TradeSignalFilter:
    """
    Server-Side Guard middleware that filters out non-trade signals.

    This implements the "Silent Ingress" pattern:
    - Agent -> Event Bus -> [Filter Middleware] -> Database/WebSocket
    - Only TRADE_SIGNAL events are allowed to trigger database writes and WebSocket emissions
    - All other events are routed to hidden log files or discarded
    """

    def __init__(self):
        # Whitelist of event types that are considered trade signals
        self._trade_signal_types: set[str] = {
            "TRADE_SIGNAL",
            "BUY_SIGNAL",
            "SELL_SIGNAL",
            "EXECUTION_SIGNAL",
        }

        # Blacklist of event types that should be filtered out (noise)
        self._noise_types: set[str] = {
            "agent_log",
            "info",
            "debug",
            "hold",
            "heartbeat",
            "system_metric",
            "runtime_status",
        }

        # Events that should be logged but not broadcast
        self._log_only_types: set[str] = {
            "agent_log",
            "info",
            "debug",
            "system_metric",
            "runtime_status",
        }

        # Events that should be completely discarded
        self._discard_types: set[str] = {
            "hold",
            "heartbeat",
        }

        self.logger = logging.getLogger(__name__)

    def is_trade_signal(self, event: dict[str, Any]) -> bool:
        """
        Determine if an event is a trade signal that should be processed.

        Args:
            event: The event dictionary from the stream

        Returns:
            True if the event is a trade signal, False otherwise
        """
        event_type = str(event.get("type") or event.get("event_type", ""))

        # Check if it's explicitly a trade signal type
        if event_type in self._trade_signal_types:
            return True

        # Check payload for trade signal indicators
        payload = event.get("payload", {})
        if isinstance(payload, dict):
            payload_type = str(payload.get("type") or payload.get("signal_type", ""))
            if payload_type in self._trade_signal_types:
                return True

            # Check for BUY/SELL indicators in payload
            action = str(payload.get("action") or payload.get("side", "")).upper()
            if action in {"BUY", "SELL"}:
                return True

            # Check for trade-related keywords
            text_content = str(payload.get("message") or payload.get("content", "")).lower()
            trade_keywords = {"buy", "sell", "trade", "order", "position", "enter", "exit"}
            if any(keyword in text_content for keyword in trade_keywords):
                # Only consider it a trade signal if it has clear intent
                if any(
                    word in text_content for word in ["signal", "recommend", "execute", "place"]
                ):
                    return True

        return False

    def should_log_only(self, event: dict[str, Any]) -> bool:
        """
        Determine if an event should be logged but not broadcast.

        Args:
            event: The event dictionary from the stream

        Returns:
            True if the event should be logged only, False otherwise
        """
        event_type = str(event.get("type") or event.get("event_type", ""))
        return event_type in self._log_only_types

    def should_discard(self, event: dict[str, Any]) -> bool:
        """
        Determine if an event should be completely discarded.

        Args:
            event: The event dictionary from the stream

        Returns:
            True if the event should be discarded, False otherwise
        """
        event_type = str(event.get("type") or event.get("event_type", ""))
        return event_type in self._discard_types

    def filter_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """
        Filter an event and return the appropriate action.

        Args:
            event: The event dictionary from the stream

        Returns:
            Dictionary with action and optionally the filtered event:
            {
                "action": "process" | "log_only" | "discard",
                "event": <filtered_event> (only for "process" and "log_only"),
                "reason": <string> (for debugging)
            }
        """
        msg_id = str(event.get("msg_id", "unknown"))
        event_type = str(event.get("type") or event.get("event_type", "unknown"))

        # Check if it's a trade signal first (highest priority)
        if self.is_trade_signal(event):
            log_structured(
                "debug",
                "trade_signal_filter_allowed",
                msg_id=msg_id,
                event_type=event_type,
                reason="trade_signal_detected",
            )
            return {
                "action": "process",
                "event": event,
                "reason": "trade_signal_detected",
            }

        # Check if it should be logged only
        if self.should_log_only(event):
            log_structured(
                "debug",
                "trade_signal_filter_log_only",
                msg_id=msg_id,
                event_type=event_type,
                reason="log_only_event",
            )
            return {
                "action": "log_only",
                "event": event,
                "reason": "log_only_event",
            }

        # Check if it should be discarded
        if self.should_discard(event):
            log_structured(
                "debug",
                "trade_signal_filter_discarded",
                msg_id=msg_id,
                event_type=event_type,
                reason="noise_event",
            )
            return {
                "action": "discard",
                "reason": "noise_event",
            }

        # Default: log only for unknown event types
        log_structured(
            "warning",
            "trade_signal_filter_unknown_type",
            msg_id=msg_id,
            event_type=event_type,
            reason="unknown_event_type_default_log_only",
        )
        return {
            "action": "log_only",
            "event": event,
            "reason": "unknown_event_type_default_log_only",
        }

    def get_filter_stats(self) -> dict[str, Any]:
        """
        Get statistics about the filter performance.

        Returns:
            Dictionary with filter statistics
        """
        return {
            "trade_signal_types": list(self._trade_signal_types),
            "noise_types": list(self._noise_types),
            "log_only_types": list(self._log_only_types),
            "discard_types": list(self._discard_types),
        }


# Global filter instance
_trade_signal_filter = TradeSignalFilter()


def get_trade_signal_filter() -> TradeSignalFilter:
    """Get the global trade signal filter instance."""
    return _trade_signal_filter


def is_trade_signal_event(event: dict[str, Any]) -> bool:
    """
    Convenience function to check if an event is a trade signal.

    Args:
        event: The event dictionary from the stream

    Returns:
        True if the event is a trade signal, False otherwise
    """
    return _trade_signal_filter.is_trade_signal(event)


def filter_trade_event(event: dict[str, Any]) -> dict[str, Any]:
    """
    Convenience function to filter a trade event.

    Args:
        event: The event dictionary from the stream

    Returns:
        Dictionary with action and optionally the filtered event
    """
    return _trade_signal_filter.filter_event(event)
