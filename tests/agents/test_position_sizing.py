"""Tests for position sizing logic in ExecutionEngine."""

from unittest.mock import AsyncMock, patch

import pytest

from api.constants import (
    FieldName,
)
from api.runtime_state import set_db_available
from api.services.execution.brokers.paper import PaperBroker
from api.services.execution.execution_engine import ExecutionEngine


@pytest.mark.asyncio
async def test_position_sizing_high_confidence_low_volatility():
    """Test position sizing with high confidence and low volatility."""

    # Mock dependencies
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    mock_redis = AsyncMock()
    mock_broker = AsyncMock(spec=PaperBroker)

    execution_engine = ExecutionEngine(mock_bus, mock_dlq, mock_redis, mock_broker)

    # Test data: high confidence, low volatility
    order_data = {
        FieldName.STRATEGY_ID: "test-strategy",
        FieldName.SYMBOL: "TSLA",
        FieldName.ACTION: "buy",
        FieldName.QTY: 1.0,
        FieldName.PRICE: 380.0,
        FieldName.CONFIDENCE: 0.8,  # High confidence
        FieldName.PCT: 1.0,  # Low volatility (1%)
        FieldName.TRACE_ID: "test-trace-123",
    }

    # Mock broker response
    mock_broker.place_order.return_value = {
        FieldName.FILL_PRICE: 381.0,
        "filled_qty": 3.0,  # Should be 3x due to high confidence
    }

    # Mock position lookup (no existing position)
    with patch.object(execution_engine, "_upsert_position", return_value={}):
        with patch.object(execution_engine, "_insert_audit_log"):
            with patch.object(execution_engine, "_insert_audit_log"):
                # Test in-memory mode
                set_db_available(False)

                await execution_engine.process(order_data)

                # Verify position sizing was applied
                assert mock_broker.place_order.called
                call_args = mock_broker.place_order.call_args
                actual_qty = call_args[0][2]  # qty parameter

                # High confidence (0.8) + low volatility (1%) = 3x multiplier
                assert actual_qty == 3.0


@pytest.mark.asyncio
async def test_position_sizing_medium_confidence_moderate_volatility():
    """Test position sizing with medium confidence and moderate volatility."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    mock_redis = AsyncMock()
    mock_broker = AsyncMock(spec=PaperBroker)

    execution_engine = ExecutionEngine(mock_bus, mock_dlq, mock_redis, mock_broker)

    # Test data: medium confidence, moderate volatility
    order_data = {
        FieldName.STRATEGY_ID: "test-strategy",
        FieldName.SYMBOL: "TSLA",
        FieldName.ACTION: "buy",
        FieldName.QTY: 1.0,
        FieldName.PRICE: 380.0,
        FieldName.CONFIDENCE: 0.6,  # Medium confidence
        FieldName.PCT: 2.5,  # Moderate volatility (2.5%)
        FieldName.TRACE_ID: "test-trace-123",
    }

    mock_broker.place_order.return_value = {
        FieldName.FILL_PRICE: 381.0,
        "filled_qty": 2.0,  # Should be 2x due to medium confidence
    }

    with patch.object(execution_engine, "_upsert_position", return_value={}):
        with patch.object(execution_engine, "_upsert_position", return_value={}):
            with patch.object(execution_engine, "_insert_audit_log"):
                with patch.object(execution_engine, "_insert_audit_log"):
                    set_db_available(False)

                    await execution_engine.process(order_data)

                    call_args = mock_broker.place_order.call_args
                    actual_qty = call_args[0][2]

                    # Medium confidence (0.6) + moderate volatility (2.5%) = 2x multiplier
                    assert actual_qty == 2.0


@pytest.mark.asyncio
async def test_position_sizing_low_confidence_high_volatility():
    """Test position sizing with low confidence and high volatility."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    mock_redis = AsyncMock()
    mock_broker = AsyncMock(spec=PaperBroker)

    execution_engine = ExecutionEngine(mock_bus, mock_dlq, mock_redis, mock_broker)

    # Test data: low confidence, high volatility
    order_data = {
        FieldName.STRATEGY_ID: "test-strategy",
        FieldName.SYMBOL: "TSLA",
        FieldName.ACTION: "buy",
        FieldName.QTY: 1.0,
        FieldName.PRICE: 380.0,
        FieldName.CONFIDENCE: 0.3,  # Low confidence
        FieldName.PCT: 4.0,  # High volatility (4%)
        FieldName.TRACE_ID: "test-trace-123",
    }

    mock_broker.place_order.return_value = {
        FieldName.FILL_PRICE: 381.0,
        "filled_qty": 1.0,  # Should be 1x due to low confidence
    }

    with patch.object(execution_engine, "_upsert_position", return_value={}):
        with patch.object(execution_engine, "_upsert_position", return_value={}):
            with patch.object(execution_engine, "_insert_audit_log"):
                with patch.object(execution_engine, "_insert_audit_log"):
                    set_db_available(False)

                    await execution_engine.process(order_data)

                    call_args = mock_broker.place_order.call_args
                    actual_qty = call_args[0][2]

                    # Low confidence (0.3) + high volatility (4%) = 1x multiplier
                    assert actual_qty == 1.0


@pytest.mark.asyncio
async def test_position_sizing_minimum_quantity_guaranteed():
    """Test that minimum quantity of 1.0 is always guaranteed."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    mock_redis = AsyncMock()
    mock_broker = AsyncMock(spec=PaperBroker)

    execution_engine = ExecutionEngine(mock_bus, mock_dlq, mock_redis, mock_broker)

    # Test data with very small base quantity
    order_data = {
        FieldName.STRATEGY_ID: "test-strategy",
        FieldName.SYMBOL: "TSLA",
        FieldName.ACTION: "buy",
        FieldName.QTY: 0.1,  # Very small base quantity
        FieldName.PRICE: 380.0,
        FieldName.CONFIDENCE: 0.9,  # High confidence
        FieldName.PCT: 0.5,  # Low volatility
        FieldName.TRACE_ID: "test-trace-123",
    }

    mock_broker.place_order.return_value = {
        FieldName.FILL_PRICE: 381.0,
        "filled_qty": 1.0,  # Should be minimum 1.0
    }

    with patch.object(execution_engine, "_upsert_position", return_value={}):
        with patch.object(execution_engine, "_upsert_position", return_value={}):
            with patch.object(execution_engine, "_insert_audit_log"):
                with patch.object(execution_engine, "_insert_audit_log"):
                    set_db_available(False)

                    await execution_engine.process(order_data)

                    call_args = mock_broker.place_order.call_args
                    actual_qty = call_args[0][2]

                    # Should be minimum 1.0 regardless of base quantity
                    assert actual_qty == 1.0


@pytest.mark.asyncio
async def test_position_sizing_database_mode():
    """Test that position sizing works correctly in database mode."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    mock_redis = AsyncMock()
    mock_broker = AsyncMock(spec=PaperBroker)

    execution_engine = ExecutionEngine(mock_bus, mock_dlq, mock_redis, mock_broker)

    order_data = {
        FieldName.STRATEGY_ID: "test-strategy",
        FieldName.SYMBOL: "TSLA",
        FieldName.ACTION: "buy",
        FieldName.QTY: 1.0,
        FieldName.PRICE: 380.0,
        FieldName.CONFIDENCE: 0.8,
        FieldName.PCT: 1.0,
        FieldName.TRACE_ID: "test-trace-123",
    }

    mock_broker.place_order.return_value = {
        FieldName.FILL_PRICE: 381.0,
        "filled_qty": 3.0,
    }

    # Mock database session
    with patch(
        "api.services.execution.execution_engine.AsyncSessionFactory"
    ) as mock_session_factory:
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session

        with patch.object(execution_engine, "_upsert_position", return_value={}):
            with patch.object(execution_engine, "_insert_audit_log"):
                set_db_available(True)  # Database mode

                await execution_engine.process(order_data)

                # Verify database operations were called
                assert mock_session.execute.called
                assert mock_session.commit.called

                # Verify position sizing was applied
                call_args = mock_broker.place_order.call_args
                actual_qty = call_args[0][2]
                assert actual_qty == 3.0


@pytest.mark.asyncio
async def test_position_sizing_sell_orders():
    """Test that position sizing works correctly for sell orders."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    mock_redis = AsyncMock()
    mock_broker = AsyncMock(spec=PaperBroker)

    execution_engine = ExecutionEngine(mock_bus, mock_dlq, mock_redis, mock_broker)

    # Test data for sell order
    order_data = {
        FieldName.STRATEGY_ID: "test-strategy",
        FieldName.SYMBOL: "TSLA",
        FieldName.ACTION: "sell",
        FieldName.QTY: 1.0,
        FieldName.PRICE: 380.0,
        FieldName.CONFIDENCE: 0.8,
        FieldName.PCT: 1.0,
        FieldName.TRACE_ID: "test-trace-123",
    }

    mock_broker.place_order.return_value = {
        FieldName.FILL_PRICE: 379.0,
        "filled_qty": 3.0,  # Should be 3x due to high confidence
    }

    with patch.object(execution_engine, "_upsert_position", return_value={}):
        with patch.object(execution_engine, "_upsert_position", return_value={}):
            with patch.object(execution_engine, "_insert_audit_log"):
                with patch.object(execution_engine, "_insert_audit_log"):
                    set_db_available(False)

                    await execution_engine.process(order_data)

                    call_args = mock_broker.place_order.call_args
                    actual_qty = call_args[0][2]

                    # Position sizing should apply to sell orders too
                    assert actual_qty == 3.0


@pytest.mark.asyncio
async def test_position_sizing_composite_score_fallback():
    """Test that composite_score is used when confidence is not available."""

    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    mock_redis = AsyncMock()
    mock_broker = AsyncMock(spec=PaperBroker)

    execution_engine = ExecutionEngine(mock_bus, mock_dlq, mock_redis, mock_broker)

    # Test data with composite_score instead of confidence
    order_data = {
        FieldName.STRATEGY_ID: "test-strategy",
        FieldName.SYMBOL: "TSLA",
        FieldName.ACTION: "buy",
        FieldName.QTY: 1.0,
        FieldName.PRICE: 380.0,
        FieldName.COMPOSITE_SCORE: 0.75,  # Use composite_score
        FieldName.PCT: 1.0,
        FieldName.TRACE_ID: "test-trace-123",
    }

    mock_broker.place_order.return_value = {
        FieldName.FILL_PRICE: 381.0,
        "filled_qty": 2.0,  # Should be 2x due to medium-high confidence
    }

    with patch.object(execution_engine, "_upsert_position", return_value={}):
        with patch.object(execution_engine, "_upsert_position", return_value={}):
            with patch.object(execution_engine, "_insert_audit_log"):
                with patch.object(execution_engine, "_insert_audit_log"):
                    set_db_available(False)

                    await execution_engine.process(order_data)

                    call_args = mock_broker.place_order.call_args
                    actual_qty = call_args[0][2]

                    # Composite score 0.75 + low volatility = 2x multiplier
                    assert actual_qty == 2.0
