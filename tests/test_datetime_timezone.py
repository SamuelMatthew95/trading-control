"""Test timezone-aware datetime handling in models."""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import inspect

# Import all models to ensure they are registered with Base
from api.core.models import (
    Order, SystemMetric, Trade, AgentPerformance, Run, AgentRun, 
    TraceStep, VectorMemoryRecord, StrategyDNA, Insight, 
    FeedbackJob, Signal, TaskTypeBaseline, SystemState
)
from api.database import Base


class TestDateTimeTimezone:
    """Test that all DateTime columns are timezone-aware."""

    @pytest.mark.asyncio
    async def test_order_datetime_columns_are_timezone_aware(self):
        """Test Order model DateTime columns have timezone=True."""
        # Check Order model columns
        order_columns = Order.__table__.columns
        created_at_col = order_columns['created_at']
        filled_at_col = order_columns['filled_at']
        
        # Assert timezone=True
        assert created_at_col.type.timezone, "Order.created_at should have timezone=True"
        assert filled_at_col.type.timezone, "Order.filled_at should have timezone=True"
        
        # Test default function produces timezone-aware datetime
        default_created = Order.created_at.default
        assert hasattr(default_created, 'arg'), "Order.created_at default should be callable"
        test_datetime = default_created.arg(None)  # Pass context=None for testing
        assert test_datetime.tzinfo is not None, "Order.created_at default should be timezone-aware"
        assert test_datetime.tzinfo == timezone.utc, "Order.created_at should use UTC timezone"

    @pytest.mark.asyncio
    async def test_system_metric_datetime_columns_are_timezone_aware(self):
        """Test SystemMetric model DateTime columns have timezone=True."""
        # Check SystemMetric model columns
        metric_columns = SystemMetric.__table__.columns
        timestamp_col = metric_columns['timestamp']
        
        # Assert timezone=True
        assert timestamp_col.type.timezone, "SystemMetric.timestamp should have timezone=True"
        
        # Test default function produces timezone-aware datetime
        default_timestamp = SystemMetric.timestamp.default
        assert hasattr(default_timestamp, 'arg'), "SystemMetric.timestamp default should be callable"
        test_datetime = default_timestamp.arg(None)  # Pass context=None for testing
        assert test_datetime.tzinfo is not None, "SystemMetric.timestamp default should be timezone-aware"
        assert test_datetime.tzinfo == timezone.utc, "SystemMetric.timestamp should use UTC timezone"

    @pytest.mark.asyncio
    async def test_all_datetime_columns_have_timezone(self):
        """Test ALL DateTime columns across all models have timezone=True."""
        models_with_datetime = [
            Trade, AgentPerformance, Run, AgentRun, TraceStep,
            VectorMemoryRecord, StrategyDNA, Insight, FeedbackJob,
            Signal, TaskTypeBaseline, SystemState, Order, SystemMetric
        ]
        
        for model in models_with_datetime:
            table = model.__table__
            for column_name, column in table.columns.items():
                if hasattr(column.type, 'timezone'):  # It's a DateTime column
                    assert column.type.timezone, f"{model.__name__}.{column_name} should have timezone=True"

    @pytest.mark.asyncio
    async def test_insert_order_with_aware_datetime_no_error(self):
        """Test inserting Order with timezone-aware datetime doesn't raise error."""
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False}
        )
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            AsyncSessionLocal = async_sessionmaker(
                engine, expire_on_commit=False, class_=AsyncSession
            )
            async with AsyncSessionLocal() as session:
                # Create order with timezone-aware datetime
                order = Order(
                    id="test-order-id-123",  # Provide primary key
                    strategy_id="test-strategy",
                    symbol="BTC/USD",
                    side="buy",
                    qty="1.00000000",
                    price="50000.00000000",
                    status="pending",
                    idempotency_key="test-key-123",
                    created_at=datetime.now(timezone.utc)
                )
                
                session.add(order)
                await session.commit()
                
                # Verify it was saved
                result = await session.execute(
                    text("SELECT COUNT(*) FROM orders WHERE idempotency_key = :key"),
                    {"key": "test-key-123"}
                )
                count = result.scalar()
                assert count == 1, "Order should be saved with timezone-aware datetime"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_insert_system_metric_with_aware_datetime_no_error(self):
        """Test inserting SystemMetric with timezone-aware datetime doesn't raise error."""
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False}
        )
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            AsyncSessionLocal = async_sessionmaker(
                engine, expire_on_commit=False, class_=AsyncSession
            )
            async with AsyncSessionLocal() as session:
                # Create metric with timezone-aware datetime
                metric = SystemMetric(
                    id="test-metric-id-456",  # Provide primary key
                    metric_name="test_metric",
                    value=42.5,
                    labels='{"test": "value"}',
                    timestamp=datetime.now(timezone.utc)
                )
                
                session.add(metric)
                await session.commit()
                
                # Verify it was saved
                result = await session.execute(
                    text("SELECT COUNT(*) FROM system_metrics WHERE metric_name = :name"),
                    {"name": "test_metric"}
                )
                count = result.scalar()
                assert count == 1, "SystemMetric should be saved with timezone-aware datetime"
        finally:
            await engine.dispose()

    def test_no_datetime_utcnow_usage_in_models(self):
        """Test that datetime.utcnow is not used anywhere in models."""
        import api.core.models
        import inspect
        
        # Get source code of models module
        source = inspect.getsource(api.core.models)
        
        # Assert datetime.utcnow is not used
        assert "datetime.utcnow" not in source, "datetime.utcnow should not be used in models"
        assert "datetime.now(timezone.utc)" in source, "Should use timezone-aware datetime.now"
