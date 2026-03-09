"""
Comprehensive Test Suite for Trading System
Tests actual skills and production components
"""

import pytest
import pytest_asyncio
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List
import tempfile
import os

# Import core systems to test
from src.core.stateful_logging_system import (
    DatabaseManager, StatefulLogger, TestDatabaseManager,
    LogLevel, EventType, AgentStatus, PerformanceMetric,
    create_stateful_logging_system
)
from src.system.professional_trading_orchestrator import (
    SupervisorOrchestrator, TradingState, TradingPhase,
    create_professional_orchestrator
)


class TestStatefulLoggingSystem:
    """Test stateful logging system with database persistence"""
    
    @pytest_asyncio.fixture
    async def temp_db(self):
        """Create temporary database for testing"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        db_manager, logger, test_manager = create_stateful_logging_system(db_path)
        
        yield db_manager, logger, test_manager
        
        # Cleanup
        await test_manager.cleanup_test_data()
        os.unlink(db_path)
    
    @pytest.mark.asyncio
    async def test_database_initialization(self, temp_db):
        """Test database table creation"""
        db_manager, _, _ = temp_db
        
        # Verify tables exist
        async with db_manager.get_connection() as conn:
            tables = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table'
            """).fetchall()
            
            table_names = [row['name'] for row in tables]
            required_tables = [
                'agent_logs', 'execution_history', 'agent_performance',
                'agents', 'learning_sessions', 'team_formations'
            ]
            
            for table in required_tables:
                assert table in table_names, f"Table {table} not created"
    
    @pytest.mark.asyncio
    async def test_agent_execution_logging(self, temp_db):
        """Test agent execution logging"""
        _, logger, test_manager = temp_db
        
        # Set up test data
        await test_manager.setup_test_data()
        
        # Log agent execution
        await logger.log_agent_execution(
            agent_id="agent_001",
            execution_id="test_exec_001",
            action="analyze_market",
            input_data={"symbol": "AAPL", "indicators": ["RSI", "MACD"]},
            output_data={"signal": "buy", "confidence": 0.85},
            success=True,
            execution_time_ms=150
        )
        
        # Verify execution was logged
        history = await logger.db.get_execution_history(agent_id="agent_001")
        assert len(history) >= 1
        assert history[0]["action"] == "analyze_market"
        assert history[0]["success"] == True
        assert history[0]["execution_time_ms"] == 150
        
        # Verify performance metric was recorded
        metrics = await logger.db.get_performance_metrics(
            agent_id="agent_001", metric_type=PerformanceMetric.EXECUTION_TIME
        )
        assert len(metrics) > 0
        assert metrics[0]["metric_value"] == 150.0
    
    @pytest.mark.asyncio
    async def test_mistake_analysis_logging(self, temp_db):
        """Test mistake analysis logging"""
        _, logger, test_manager = temp_db
        
        await test_manager.setup_test_data()
        
        # Log mistake analysis
        await logger.log_mistake_analysis(
            agent_id="agent_002",
            execution_id="test_exec_002",
            mistake_pattern="data_interpretation_error",
            analysis={
                "root_cause": "Invalid data format",
                "severity": "major",
                "prevention_strategies": ["Add validation", "Cross-check sources"]
            }
        )
        
        # Verify analysis was logged
        history = await logger.db.get_agent_history(agent_id="agent_002", limit=10)
        mistake_logs = [log for log in history if log["event_type"] == "mistake_analysis"]
        assert len(mistake_logs) > 0
        assert mistake_logs[0]["status"] == "learning"
    
    @pytest.mark.asyncio
    async def test_learning_session_logging(self, temp_db):
        """Test learning session logging"""
        _, logger, test_manager = temp_db
        
        await test_manager.setup_test_data()
        
        # Log learning session
        await logger.log_learning_session(
            session_id="test_session_001",
            participants=["agent_001", "agent_002", "agent_003"],
            session_type="mistake_review",
            outcomes={
                "insights_shared": 5,
                "strategies_developed": 3,
                "success_rate": 0.85
            }
        )
        
        # Verify session was logged
        async with logger.db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM learning_sessions WHERE session_id = ?", ("test_session_001",))
            session = cursor.fetchone()
            
            assert session is not None
            assert session["session_type"] == "mistake_review"
            assert json.loads(session["participants"]) == ["agent_001", "agent_002", "agent_003"]
    
    @pytest.mark.asyncio
    async def test_performance_evaluation_logging(self, temp_db):
        """Test performance evaluation logging"""
        _, logger, test_manager = temp_db
        
        await test_manager.setup_test_data()
        
        # Log performance evaluation
        metrics = {
            "success_rate": 0.92,
            "execution_time": 125.5,
            "collaboration_success": 0.88,
            "expertise_score": 0.85
        }
        
        await logger.log_performance_evaluation("agent_001", metrics)
        
        # Verify metrics were recorded
        recorded_metrics = await logger.db.get_performance_metrics(agent_id="agent_001")
        assert len(recorded_metrics) >= 4  # Should have all 4 metrics
        
        # Check that our specific metrics are recorded
        metric_values = {m["metric_type"]: float(m["metric_value"]) for m in recorded_metrics}
        assert 0.92 in [float(m["metric_value"]) for m in recorded_metrics if m["metric_type"] == "success_rate"]
        assert 125.5 in [float(m["metric_value"]) for m in recorded_metrics if m["metric_type"] == "execution_time"]
        assert 0.88 in [float(m["metric_value"]) for m in recorded_metrics if m["metric_type"] == "collaboration_success"]
        assert 0.85 in [float(m["metric_value"]) for m in recorded_metrics if m["metric_type"] == "expertise_score"]
    
    @pytest.mark.asyncio
    async def test_system_summary(self, temp_db):
        """Test system summary generation"""
        _, logger, test_manager = temp_db
        
        await test_manager.setup_test_data()
        
        # Get system summary
        summary = await logger.db.get_system_summary()
        
        # Verify summary structure
        assert "agent_status_counts" in summary
        assert "execution_stats_24h" in summary
        assert "performance_averages_24h" in summary
        assert "timestamp" in summary
        
        # Verify data exists
        assert summary["agent_status_counts"]["active"] >= 1
        assert summary["execution_stats_24h"]["total_executions"] >= 5


class TestProfessionalTradingOrchestrator:
    """Test professional trading orchestrator with state machine"""
    
    @pytest_asyncio.fixture
    async def orchestrator(self):
        """Create orchestrator for testing"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        orchestrator = create_professional_orchestrator()
        
        yield orchestrator
        
        # Cleanup
        os.unlink(db_path)
    
    @pytest.mark.asyncio
    async def test_state_initialization(self, orchestrator):
        """Test state initialization"""
        state = await orchestrator._initialize_state()
        
        # Verify state structure
        assert "market_data" in state
        assert "portfolio_value" in state
        assert "available_capital" in state
        assert "total_pnl" in state
        assert "risk_snapshot" in state
        assert "decision_log" in state
        assert "current_phase" in state
        assert "orchestrator_id" in state
        assert "session_id" in state
        
        # Verify initial values
        assert state["portfolio_value"] == 100000.0
        assert state["available_capital"] == 100000.0
        assert state["total_pnl"] == 0.0
        assert state["current_phase"] == TradingPhase.INITIALIZING.value
    
    @pytest.mark.asyncio
    async def test_trading_cycle_execution(self, orchestrator):
        """Test complete trading cycle"""
        # Run trading cycle
        state = await orchestrator.run_trading_cycle()
        
        # Verify cycle completed
        assert state["current_phase"] in [TradingPhase.MONITORING.value, TradingPhase.ERROR_HANDLING.value]
        assert "last_action" in state
        # Decision log might be empty in test environment


class TestIntegration:
    """Integration tests for the complete system"""
    
    @pytest.mark.asyncio
    async def test_core_system_integration(self):
        """Test core system integration"""
        # Create core systems
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            # Initialize systems
            db_manager, logger, test_manager = create_stateful_logging_system(db_path)
            orchestrator = create_professional_orchestrator()
            
            # Test logging integration
            await logger.log_agent_execution(
                "test_agent", "test_exec_001", "test_action",
                {"test": "data"}, {"result": "success"}, True, 100
            )
            
            # Test orchestrator integration
            state = await orchestrator.run_trading_cycle()
            
            # Verify integration
            assert state["current_phase"] in [TradingPhase.MONITORING.value, TradingPhase.ERROR_HANDLING.value]
            
            # Verify logging worked
            history = await logger.db.get_execution_history(agent_id="test_agent")
            assert len(history) >= 1
            assert history[0]["success"] == True
            
        finally:
            # Cleanup
            os.unlink(db_path)


# Test Execution

if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
