"""Tests for api/services/websocket_broadcaster.py.

Regression coverage for:
- Fix: FieldName.PRICE_UPDATE (nonexistent attribute) replaced with plain string
  "price_update" in the STREAM_MARKET_EVENTS branch of _transform_stream_message.
"""

from __future__ import annotations

import json

import pytest

from api.constants import FieldName, STREAM_MARKET_EVENTS
from api.services.websocket_broadcaster import WebSocketBroadcaster


@pytest.fixture
def broadcaster() -> WebSocketBroadcaster:
    return WebSocketBroadcaster()


# ---------------------------------------------------------------------------
# STREAM_MARKET_EVENTS — price_update path
# ---------------------------------------------------------------------------


def test_transform_market_event_returns_price_update(broadcaster: WebSocketBroadcaster) -> None:
    """Well-formed market-event payload must be transformed to a price_update message."""
    inner = {
        FieldName.SYMBOL: "BTC/USD",
        FieldName.PRICE: 50000.0,
        FieldName.TS: "2026-01-01T00:00:00Z",
    }
    payload = {FieldName.PAYLOAD: json.dumps(inner)}

    result = broadcaster._transform_stream_message(
        stream=STREAM_MARKET_EVENTS,
        msg_id="1-0",
        payload=payload,
    )

    assert result is not None
    assert result[FieldName.TYPE] == "price_update"
    assert FieldName.SYMBOL in result
    assert result[FieldName.SYMBOL] == "BTC/USD"


def test_transform_market_event_no_symbol_returns_none(broadcaster: WebSocketBroadcaster) -> None:
    """Market-event payload with no symbol in the inner dict must be filtered (returns None)."""
    inner = {FieldName.PRICE: 50000.0, FieldName.TS: "2026-01-01T00:00:00Z"}
    payload = {FieldName.PAYLOAD: json.dumps(inner)}

    result = broadcaster._transform_stream_message(
        stream=STREAM_MARKET_EVENTS,
        msg_id="2-0",
        payload=payload,
    )

    assert result is None


def test_transform_market_event_no_attribute_error_regression(
    broadcaster: WebSocketBroadcaster,
) -> None:
    """Regression: calling _transform_stream_message for STREAM_MARKET_EVENTS must NOT raise
    AttributeError.  Before the fix, FieldName.PRICE_UPDATE was accessed but does not exist on
    FieldName, causing a crash on every market-event message."""
    inner = {
        FieldName.SYMBOL: "ETH/USD",
        FieldName.PRICE: 3000.0,
        FieldName.TS: "2026-01-01T00:00:00Z",
    }
    payload = {FieldName.PAYLOAD: json.dumps(inner)}

    # Must not raise AttributeError (or any other exception)
    try:
        broadcaster._transform_stream_message(
            stream=STREAM_MARKET_EVENTS,
            msg_id="3-0",
            payload=payload,
        )
    except AttributeError as exc:
        pytest.fail(f"AttributeError raised — fix may have been reverted: {exc}")


def test_transform_market_event_flat_payload_with_symbol(broadcaster: WebSocketBroadcaster) -> None:
    """Flat payload (no nested PAYLOAD key) containing SYMBOL is also handled."""
    payload = {
        FieldName.SYMBOL: "SOL/USD",
        FieldName.PRICE: 145.0,
        FieldName.TS: "2026-01-01T00:00:00Z",
    }

    result = broadcaster._transform_stream_message(
        stream=STREAM_MARKET_EVENTS,
        msg_id="4-0",
        payload=payload,
    )

    assert result is not None
    assert result[FieldName.TYPE] == "price_update"
    assert result[FieldName.SYMBOL] == "SOL/USD"
