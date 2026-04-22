"""Tests for signal generation logging and symbol diversity."""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import time

from api.constants import (
    AGENT_SIGNAL,
    STREAM_AGENT_LOGS,
    STREAM_SIGNALS,
    FieldName,
    MarketDirection,
    SignalStrength,
    SignalType,
    LogType,
)
from api.services.signal_generator import SignalGenerator
from api.services.events import EventBus

@pytest.mark.asyncio
async def test_signal_generator_symbol_logging():
    """Test that SignalGenerator logs all symbols correctly."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    signal_gen = SignalGenerator(mock_bus, mock_dlq)

    # Test data for different symbols
    symbols_data = [
        {
            FieldName.SYMBOL: "BTC/USD",
            FieldName.PRICE: 45000.0,
            FieldName.PCT: 2.5,
            FieldName.TRACE_ID: "trace-btc-123",
        },
        {
            FieldName.SYMBOL: "ETH/USD",
            FieldName.PRICE: 3000.0,
            FieldName.PCT: -1.8,
            FieldName.TRACE_ID: "trace-eth-456",
        },
        {
            FieldName.SYMBOL: "TSLA",
            FieldName.PRICE: 380.0,
            FieldName.PCT: 3.2,
            FieldName.TRACE_ID: "trace-tsla-789",
        },
    ]

    with patch.object(signal_gen, "_resolve_agent_pool_id", return_value="pool-123"):
        with patch.object(signal_gen, "_begin_run", return_value=(True, 1)):
            with patch.object(signal_gen, "_persist_signal_complete"):
                with patch("api.services.signal_generator.write_heartbeat"):
                    for data in symbols_data:
                        await signal_gen.process(data)

                    # Verify signals were published for all symbols
                    assert mock_bus.publish.call_count == 3

                    # Check published signals contain correct symbol data
                    published_calls = mock_bus.publish.call_args_list
                    symbols_published = [call[0][1][FieldName.SYMBOL] for call in published_calls]
                    assert "BTC/USD" in symbols_published
                    assert "ETH/USD" in symbols_published
                    assert "TSLA" in symbols_published


@pytest.mark.asyncio
async def test_signal_generator_classification_logging():
    """Test that signal classification is logged with proper details."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    signal_gen = SignalGenerator(mock_bus, mock_dlq)

    # Test data with high volatility
    signal_data = {
        FieldName.SYMBOL: "TSLA",
        FieldName.PRICE: 380.0,
        FieldName.PCT: 4.5,  # High volatility
        FieldName.TRACE_ID: "trace-tsla-high-123",
    }

    with patch("api.services.signal_generator.log_structured") as mock_log:
        with patch.object(signal_gen, "_resolve_agent_pool_id", return_value="pool-123"):
            with patch.object(signal_gen, "_begin_run", return_value=(True, 1)):
                with patch.object(signal_gen, "_persist_signal_complete"):
                    with patch("api.services.signal_generator.write_heartbeat"):
                        await signal_gen.process(signal_data)

                        # Verify classification logging was called
                        mock_log.assert_called()

                        # Check the logged classification details
                        log_call = mock_log.call_args
                        log_data = log_call[1]

                        assert log_data[0] == f"[{AGENT_SIGNAL}] signal_classification"
                        assert log_data[1]["symbol"] == "TSLA"
                        assert log_data[1]["price"] == 380.0
                        assert log_data[1]["pct"] == 4.5
                        assert log_data[1]["abs_pct"] == 4.5
                        assert log_data[1]["direction"] == MarketDirection.BULLISH.value


@pytest.mark.asyncio
async def test_signal_generator_signal_strength_classification():
    """Test that signal strength is correctly classified and logged."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    signal_gen = SignalGenerator(mock_bus, mock_dlq)

    # Test cases for different volatility levels
    test_cases = [
        {
            "pct": 0.5,
            "expected_type": SignalType.PRICE_UPDATE,
            "expected_strength": SignalStrength.LOW,
        },
        {
            "pct": 2.0,
            "expected_type": SignalType.MOMENTUM,
            "expected_strength": SignalStrength.NORMAL,
        },
        {
            "pct": 4.0,
            "expected_type": SignalType.STRONG_MOMENTUM,
            "expected_strength": SignalStrength.HIGH,
        },
        {
            "pct": -1.0,
            "expected_type": SignalType.PRICE_UPDATE,
            "expected_strength": SignalStrength.LOW,
        },
        {
            "pct": -2.5,
            "expected_type": SignalType.MOMENTUM,
            "expected_strength": SignalStrength.NORMAL,
        },
        {
            "pct": -5.0,
            "expected_type": SignalType.STRONG_MOMENTUM,
            "expected_strength": SignalStrength.HIGH,
        },
    ]

    with patch.object(signal_gen, "_resolve_agent_pool_id", return_value="pool-123"):
        with patch.object(signal_gen, "_begin_run", return_value=(True, 1)):
            with patch.object(signal_gen, "_persist_signal_complete"):
                with patch("api.services.signal_generator.write_heartbeat"):
                    for case in test_cases:
                        signal_data = {
                            FieldName.SYMBOL: "TEST",
                            FieldName.PRICE: 100.0,
                            FieldName.PCT: case["pct"],
                            FieldName.TRACE_ID: f"trace-{case['pct']}",
                        }

                        await signal_gen.process(signal_data)

                        # Check the published signal
                        published_call = mock_bus.publish.call_args_list[-1]
                        published_signal = published_call[0][1]

                        assert published_signal["type"] == case["expected_type"].value
                        assert published_signal["strength"] == case["expected_strength"].value


@pytest.mark.asyncio
async def test_signal_generator_direction_classification():
    """Test that market direction is correctly classified."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    signal_gen = SignalGenerator(mock_bus, mock_dlq)

    # Test cases for different price changes
    test_cases = [
        {"pct": 2.5, "expected_direction": MarketDirection.BULLISH, "expected_action": "buy"},
        {"pct": -1.8, "expected_direction": MarketDirection.BEARISH, "expected_action": "sell"},
        {"pct": 0.0, "expected_direction": MarketDirection.NEUTRAL, "expected_action": "hold"},
    ]

    with patch.object(signal_gen, "_resolve_agent_pool_id", return_value="pool-123"):
        with patch.object(signal_gen, "_begin_run", return_value=(True, 1)):
            with patch.object(signal_gen, "_persist_signal_complete"):
                with patch("api.services.signal_generator.write_heartbeat"):
                    for case in test_cases:
                        signal_data = {
                            FieldName.SYMBOL: "TEST",
                            FieldName.PRICE: 100.0,
                            FieldName.PCT: case["pct"],
                            FieldName.TRACE_ID: f"trace-{case['pct']}",
                        }

                        await signal_gen.process(signal_data)

                        # Check the published signal
                        published_call = mock_bus.publish.call_args_list[-1]
                        published_signal = published_call[0][1]

                        assert published_signal["direction"] == case["expected_direction"].value
                        assert published_signal["action"] == case["expected_action"]


@pytest.mark.asyncio
async def test_signal_generator_comprehensive_signal_payload():
    """Test that signal payload contains all required fields with correct values."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    signal_gen = SignalGenerator(mock_bus, mock_dlq)

    signal_data = {
        FieldName.SYMBOL: "TSLA",
        FieldName.PRICE: 380.0,
        FieldName.PCT: 2.5,
        FieldName.TRACE_ID: "trace-tsla-123",
    }

    with patch.object(signal_gen, "_resolve_agent_pool_id", return_value="pool-123"):
        with patch.object(signal_gen, "_begin_run", return_value=(True, 1)):
            with patch.object(signal_gen, "_persist_signal_complete"):
                with patch("api.services.signal_generator.write_heartbeat"):
                    await signal_gen.process(signal_data)

                    # Check the published signal payload
                    published_call = mock_bus.publish.call_args_list[-1]
                    published_signal = published_call[0][1]

                    # Verify all required fields are present
                    assert FieldName.TYPE in published_signal
                    assert FieldName.SYMBOL in published_signal
                    assert FieldName.PRICE in published_signal
                    assert FieldName.PCT in published_signal
                    assert FieldName.DIRECTION in published_signal
                    assert FieldName.STRENGTH in published_signal
                    assert FieldName.COMPOSITE_SCORE in published_signal
                    assert FieldName.CONFIDENCE in published_signal
                    assert FieldName.ACTION in published_signal
                    assert FieldName.TRACE_ID in published_signal
                    assert FieldName.TS in published_signal
                    assert FieldName.SOURCE in published_signal
                    assert FieldName.MSG_ID in published_signal

                    # Verify values are correct
                    assert published_signal[FieldName.SYMBOL] == "TSLA"
                    assert published_signal[FieldName.PRICE] == 380.0
                    assert published_signal[FieldName.PCT] == 2.5
                    assert published_signal[FieldName.TRACE_ID] == "trace-tsla-123"
                    assert published_signal[FieldName.SOURCE] == AGENT_SIGNAL


@pytest.mark.asyncio
async def test_signal_generator_detailed_publish_logging():
    """Test that detailed signal publishing is logged."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    signal_gen = SignalGenerator(mock_bus, mock_dlq)

    signal_data = {
        FieldName.SYMBOL: "TSLA",
        FieldName.PRICE: 380.0,
        FieldName.PCT: 2.5,
        FieldName.TRACE_ID: "trace-tsla-123",
    }

    with patch("api.services.signal_generator.log_structured") as mock_log:
        with patch.object(signal_gen, "_resolve_agent_pool_id", return_value="pool-123"):
            with patch.object(signal_gen, "_begin_run", return_value=(True, 1)):
                with patch.object(signal_gen, "_persist_signal_complete"):
                    with patch("api.services.signal_generator.write_heartbeat"):
                        await signal_gen.process(signal_data)

                        # Verify detailed publish logging was called
                        publish_log_calls = [
                            call
                            for call in mock_log.call_args_list
                            if "signal_published" in str(call)
                        ]
                        assert len(publish_log_calls) > 0

                        # Check the logged publish details
                        publish_log_call = publish_log_calls[0]
                        log_data = publish_log_call[1]

                        assert log_data[0] == f"[{AGENT_SIGNAL}] signal_published"
                        assert log_data[1]["symbol"] == "TSLA"
                        assert log_data[1]["price"] == 380.0
                        assert log_data[1]["pct"] == 2.5
                        assert log_data[1]["direction"] == MarketDirection.BULLISH.value
                        assert log_data[1]["action"] == "buy"
                        assert log_data[1]["confidence"] > 0
                        assert log_data[1]["trace_id"] == "trace-tsla-123"


@pytest.mark.asyncio
async def test_signal_generator_all_tracked_symbols():
    """Test that all 6 tracked symbols can generate signals."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    signal_gen = SignalGenerator(mock_bus, mock_dlq)

    # All tracked symbols
    tracked_symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "AAPL", "TSLA", "SPY"]

    with patch.object(signal_gen, "_resolve_agent_pool_id", return_value="pool-123"):
        with patch.object(signal_gen, "_begin_run", return_value=(True, 1)):
            with patch.object(signal_gen, "_persist_signal_complete"):
                with patch("api.services.signal_generator.write_heartbeat"):
                    for symbol in tracked_symbols:
                        signal_data = {
                            FieldName.SYMBOL: symbol,
                            FieldName.PRICE: 100.0 if "/" not in symbol else 10000.0,
                            FieldName.PCT: 1.5,  # Moderate volatility
                            FieldName.TRACE_ID: f"trace-{symbol.lower()}-123",
                        }

                        await signal_gen.process(signal_data)

                    # Verify signals were generated for all symbols
                    assert mock_bus.publish.call_count == len(tracked_symbols)

                    # Check all symbols were processed
                    published_calls = mock_bus.publish.call_args_list
                    symbols_processed = [call[0][1][FieldName.SYMBOL] for call in published_calls]

                    for symbol in tracked_symbols:
                        assert symbol in symbols_processed, f"Symbol {symbol} not processed"


@pytest.mark.asyncio
async def test_signal_generator_rejects_invalid_data():
    """Test that SignalGenerator properly rejects invalid market data."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    signal_gen = SignalGenerator(mock_bus, mock_dlq)

    # Test cases with invalid data
    invalid_cases = [
        {},  # Missing all fields
        {FieldName.SYMBOL: ""},  # Empty symbol
        {FieldName.SYMBOL: "TSLA", FieldName.PRICE: 0},  # Zero price
        {FieldName.SYMBOL: "TSLA", FieldName.PRICE: -10},  # Negative price
    ]

    with patch.object(signal_gen, "_resolve_agent_pool_id", return_value="pool-123"):
        with patch.object(signal_gen, "_begin_run", return_value=(True, 1)):
            with patch.object(signal_gen, "_persist_signal_complete"):
                with patch("api.services.signal_generator.write_heartbeat"):
                    for invalid_data in invalid_cases:
                        await signal_gen.process(invalid_data)

                    # No signals should be published for invalid data
                    assert mock_bus.publish.call_count == 0
