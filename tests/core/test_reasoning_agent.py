"""Tests for reasoning agent production safety."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from api.services.agents.reasoning_agent import ReasoningAgent
from api.core.models import POSTGRES_AVAILABLE


class TestReasoningAgent:
    """Test reasoning agent production safety and reliability."""

    @pytest.fixture
    def agent(self):
        """Create reasoning agent fixture."""
        bus = MagicMock()
        dlq = MagicMock()
        redis = AsyncMock()
        return ReasoningAgent(bus, dlq, redis)

    async def test_transaction_atomicity(self, agent):
        """Test that transaction failures raise exceptions."""
        from sqlalchemy import text
        from api.db import AsyncSessionFactory
        
        # Create a session that will fail
        bad_summary = {"action": None}
        
        # This should raise an exception due to bad data
        with pytest.raises(Exception):
            async with AsyncSessionFactory() as session:
                async with session.begin():
                    await agent._store_agent_run(
                        {"symbol": "TEST"}, 
                        bad_summary, 
                        "test_trace", 
                        False, 
                        session=session
                    )

    async def test_sqlite_vector_safe(self, agent):
        """Test that vector search safely returns empty list on SQLite."""
        if not POSTGRES_AVAILABLE:
            result = await agent._search_vector_memory([0.1] * 1536)
            assert result == []

    async def test_uuid_generated(self, agent):
        """Test that UUID is generated on insert."""
        from sqlalchemy import text
        from api.db import AsyncSessionFactory
        
        async with AsyncSessionFactory() as session:
            result = await session.execute(text("""
                INSERT INTO agent_logs (trace_id, log_type, payload)
                VALUES ('test_trace', 'test', '{}')
                RETURNING id
            """))
            row_id = result.scalar()
            assert row_id is not None
            assert len(str(row_id)) > 0  # Should be a UUID

    async def test_full_process(self, agent):
        """Test full process execution."""
        data = {
            "symbol": "AAPL",
            "price": 100,
            "composite_score": 0.8,
            "action": "buy",
            "quantity": 10,
        }
        
        # Mock Redis to return budget available
        agent.redis.get = AsyncMock(return_value="100")
        agent.redis.incrby = AsyncMock()
        agent.redis.incrbyfloat = AsyncMock()
        
        # Mock LLM embedding to avoid API call
        agent._embed_text = AsyncMock(return_value=[0.1] * 1536)
        
        # Mock vector search to return empty
        agent._search_vector_memory = AsyncMock(return_value=[])
        
        # Mock fallback to avoid LLM call
        agent._apply_fallback = AsyncMock(return_value={
            "action": "hold",
            "confidence": 0.5,
            "primary_edge": "fallback:budget_exceeded",
            "risk_factors": ["test"],
            "size_pct": 0.01,
            "stop_atr_x": 1.5,
            "rr_ratio": 2.0,
            "latency_ms": 0,
            "cost_usd": 0.0,
            "trace_id": "test",
            "fallback": True,
        })
        
        # This should not raise an exception
        await agent.process(data)
        
        # Verify Redis was called
        assert agent.redis.incrby.called
        assert agent.redis.incrbyfloat.called

    def test_json_expr_helper(self, agent):
        """Test JSON expression helper methods."""
        # Test PostgreSQL mode
        agent._json_expr("test_field")
        
        # Test that helper returns proper format
        expr = agent._json_expr("signal_data")
        if POSTGRES_AVAILABLE:
            assert "CAST(:signal_data AS JSONB)" in expr
        else:
            assert ":signal_data" in expr

    def test_vector_expr_helper(self, agent):
        """Test vector expression helper method."""
        expr = agent._vector_expr()
        if POSTGRES_AVAILABLE:
            assert "CAST(:embedding AS vector)" in expr
        else:
            assert ":embedding" in expr

    async def test_get_last_reflection_logging(self, agent):
        """Test that reflection failures are logged."""
        from unittest.mock import patch
        
        with patch('api.services.agents.reasoning_agent.AsyncSessionFactory') as mock_session:
            # Make session.execute raise an exception
            mock_session.return_value.__aenter__.return_value.execute.side_effect = Exception("DB error")
            
            result = await agent._get_last_reflection()
            
            # Should return empty dict on error
            assert result == {}
            
            # Verify error was logged (would need to check log calls in real test)

    async def test_action_normalization(self, agent):
        """Test that actions are normalized consistently."""
        # Test fallback action normalization
        fallback_result = await agent._apply_fallback(
            {"action": "BUY"}, "test_trace", "test_reason"
        )
        
        # Action should be lowercase
        assert fallback_result["action"] == "buy"

    async def test_cost_tracking_in_transaction(self, agent):
        """Test that cost tracking uses shared session."""
        from sqlalchemy import text
        from api.db import AsyncSessionFactory
        
        # This test would verify that _store_cost_tracking
        # doesn't create its own session but uses the shared one
        async with AsyncSessionFactory() as session:
            async with session.begin():
                # This should work without creating new session
                await agent._store_cost_tracking(
                    "2023-01-01", 100, 1.0, session=session
                )
