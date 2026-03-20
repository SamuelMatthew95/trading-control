"""Test database initialization with create_all."""

from __future__ import annotations

import asyncio
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import models to ensure they are registered with Base
from api.core.models import (
    Trade, AgentPerformance, Run, AgentRun, TraceStep, 
    VectorMemoryRecord, StrategyDNA, Insight, FeedbackJob,
    Signal, TaskTypeBaseline, SystemState, Order, SystemMetric
)
from api.database import Base


class TestDatabaseInit:
    """Test database table creation and initialization."""

    @pytest.mark.asyncio
    async def test_create_all_runs_without_errors(self):
        """Test that create_all runs without errors."""
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False},  # Fix threading issue
        )
        try:
            async with engine.begin() as conn:
                # Should not raise any exceptions
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_create_all_idempotency(self):
        """Test that calling create_all twice doesn't raise errors."""
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False},  # Fix threading issue
        )
        try:
            async with engine.begin() as conn:
                # First call
                await conn.run_sync(Base.metadata.create_all)
                
                # Second call should also work without errors
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_key_tables_exist_after_create_all(self):
        """Test that key tables exist after running create_all."""
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False},  # Fix threading issue
        )
        try:
            # Create all tables
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            # Create a session to query tables
            AsyncSessionLocal = async_sessionmaker(
                engine, expire_on_commit=False, class_=AsyncSession
            )
            async with AsyncSessionLocal() as session:
                # Check that key tables exist
                metadata_tables = set(Base.metadata.tables.keys())
                
                # Check that expected tables are in the metadata and created
                expected_tables = ["trades", "agent_performance", "runs", "orders", "system_metrics"]
                for table_name in expected_tables:
                    assert table_name in metadata_tables, f"Table '{table_name}' not found in Base.metadata.tables"
                    
                    # Verify table was created in database
                    result = await session.execute(
                        text(f"SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
                        {"table_name": table_name}
                    )
                    table_exists = result.fetchone() is not None
                    assert table_exists, f"Table '{table_name}' was not created in the database"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_all_metadata_tables_created(self):
        """Test that all tables in Base.metadata are created."""
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False},  # Fix threading issue
        )
        try:
            # Create all tables
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            # Create a session to query tables
            AsyncSessionLocal = async_sessionmaker(
                engine, expire_on_commit=False, class_=AsyncSession
            )
            async with AsyncSessionLocal() as session:
                # Verify all metadata tables exist in the database
                for table_name in Base.metadata.tables.keys():
                    result = await session.execute(
                        text(f"SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
                        {"table_name": table_name}
                    )
                    table_exists = result.fetchone() is not None
                    assert table_exists, f"Table '{table_name}' from metadata was not created"
        finally:
            await engine.dispose()

    def test_base_metadata_contains_expected_tables(self):
        """Test that Base.metadata contains the expected tables."""
        metadata_tables = set(Base.metadata.tables.keys())
        
        # Check for key tables that should be defined as models
        expected_model_tables = [
            "trades",
            "agent_performance", 
            "runs",
            "agent_runs",
            "trace_steps",
            "vector_memory_records",
            "strategy_dna",
            "insights",
            "feedback_jobs",
            "signals",
            "task_type_baselines",
            "system_state",
            "orders",
            "system_metrics"
        ]
        
        for table in expected_model_tables:
            assert table in metadata_tables, f"Expected table '{table}' not found in Base.metadata"
        
        # All tables including orders and system_metrics are now defined in SQLAlchemy models
        # and will be created by Base.metadata.create_all
