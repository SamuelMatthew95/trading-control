"""
Enhanced test suite with comprehensive coverage
Tests core functionality, integration, error handling, and performance
"""

import pytest
import pytest_asyncio
import asyncio
import json
import time
import uuid
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


class TestDataManager:
    """Factory for creating consistent test data"""
    
    @staticmethod
    def get_test_market_data() -> Dict[str, Any]:
        """Standard test market data"""
        return {
            "AAPL": {"price": 175.43, "volume": 1000000, "change": 1.2},
            "GOOGL": {"price": 140.25, "volume": 600000, "change": -0.5},
            "MSFT": {"price": 380.12, "volume": 800000, "change": 0.8}
        }
    
    @staticmethod
    def get_test_trade() -> Dict[str, Any]:
        """Standard test trade"""
        return {
            "symbol": "AAPL",
            "action": "buy", 
            "size": 10000,
            "confidence": 0.85,
            "reasoning": "Positive momentum"
        }
    
    @staticmethod
    def create_execution_record(agent_id: str, success: bool = True) -> Dict[str, Any]:
        """Create a test execution record"""
        return {
            "execution_id": f"exec_{uuid.uuid4().hex[:8]}",
            "agent_id": agent_id,
            "action": "test_action",
            "input_data": {"test": "data"},
            "output_data": {"result": "success"} if success else None,
            "success": success,
            "error_message": None if success else "Test error",
            "execution_time_ms": 100,
            "timestamp": datetime.now().isoformat()
        }


class TestStatefulLoggingSystem:
    """Test stateful logging system with comprehensive coverage"""
    
    @pytest_asyncio.fixture
    async def temp_db(self):
        """Create isolated test database"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        db_manager, logger, test_manager = create_stateful_logging_system(db_path)
        
        yield db_manager, logger, test_manager
        
        # Cleanup
        await test_manager.cleanup_test_data()
        os.unlink(db_path)
    
    async def test_database_initialization(self, temp_db):
        """
        Test database tables are created correctly.
        
        Verifies all required tables exist with proper structure.
        """
        db_manager, _, _ = temp_db
        
        async with db_manager.get_connection() as conn:
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table'
            """)
            tables = [row['name'] for row in cursor.fetchall()]
            
            required_tables = [
                'agent_logs', 'execution_history', 'agent_performance',
                'agents', 'learning_sessions', 'team_formations'
            ]
            
            for table in required_tables:
                assert table in tables, f"Table {table} not created"
    
    async def test_agent_execution_logging(self, temp_db):
        """
        Test that agent executions are logged correctly.
        
        Verifies execution history is stored with all required fields.
        """
        _, logger, _ = temp_db
        
        await logger.log_agent_execution(
            agent_id="test_agent_001",
            execution_id="test_exec_001",
            action="analyze_market",
            input_data={"symbol": "AAPL", "indicators": ["RSI", "MACD"]},
            output_data={"signal": "buy", "confidence": 0.85},
            success=True,
            execution_time_ms=150
        )
        
        # Verify execution was logged
        history = await logger.db.get_execution_history(agent_id="test_agent_001")
        assert len(history) >= 1
        assert history[0]["action"] == "analyze_market"
        assert history[0]["success"] == True
        assert history[0]["execution_time_ms"] == 150
        
        # Verify performance metric was recorded
        metrics = await logger.db.get_performance_metrics(
            agent_id="test_agent_001", metric_type=PerformanceMetric.EXECUTION_TIME
        )
        assert len(metrics) > 0
        assert float(metrics[0]["metric_value"]) == 150.0
    
    async def test_mistake_analysis_logging(self, temp_db):
        """
        Test mistake analysis logging.
        
        Verifies mistake patterns are tracked with detailed analysis.
        """
        _, logger, _ = temp_db
        
        await logger.log_mistake_analysis(
            agent_id="test_agent_002",
            execution_id="test_exec_002",
            mistake_pattern="data_interpretation_error",
            analysis={
                "root_cause": "Invalid data format",
                "severity": "major",
                "prevention_strategies": ["Add validation", "Cross-check sources"]
            }
        )
        
        # Verify analysis was logged
        history = await logger.db.get_agent_history(agent_id="test_agent_002", limit=10)
        mistake_logs = [log for log in history if log["event_type"] == "mistake_analysis"]
        assert len(mistake_logs) > 0
        assert mistake_logs[0]["status"] == "learning"
    
    async def test_performance_evaluation_logging(self, temp_db):
        """
        Test performance evaluation logging.
        
        Verifies multiple performance metrics are recorded correctly.
        """
        _, logger, _ = temp_db
        
        metrics = {
            "success_rate": 0.92,
            "execution_time": 125.5,
            "collaboration_success": 0.88,
            "expertise_score": 0.85
        }
        
        await logger.log_performance_evaluation("test_agent_001", metrics)
        
        # Verify metrics were recorded
        recorded_metrics = await logger.db.get_performance_metrics(agent_id="test_agent_001")
        assert len(recorded_metrics) >= 4  # Should have all 4 metrics
        
        # Check that our specific metrics are recorded
        metric_values = {m["metric_type"]: float(m["metric_value"]) for m in recorded_metrics}
        assert 0.92 in [float(m["metric_value"]) for m in recorded_metrics if m["metric_type"] == "success_rate"]
        assert 125.5 in [float(m["metric_value"]) for m in recorded_metrics if m["metric_type"] == "execution_time"]
        assert 0.88 in [float(m["metric_value"]) for m in recorded_metrics if m["metric_type"] == "collaboration_success"]
        assert 0.85 in [float(m["metric_value"]) for m in recorded_metrics if m["metric_type"] == "expertise_score"]
    
    async def test_system_summary(self, temp_db):
        """
        Test system summary generation.
        
        Verifies comprehensive system metrics are available.
        """
        _, logger, _ = temp_db
        
        await logger.log_agent_execution(
            "test_agent", "test_exec_001", "test_action",
            {"test": "data"}, {"result": "success"}, True, 100
        )
        
        summary = await logger.db.get_system_summary()
        
        # Verify summary structure
        assert "agent_status_counts" in summary
        assert "execution_stats_24h" in summary
        assert "performance_averages_24h" in summary
        assert "timestamp" in summary
    
    async def test_concurrent_operations(self, temp_db):
        """
        Test system handles concurrent operations.
        
        Verifies multiple operations can be executed simultaneously.
        """
        _, logger, _ = temp_db
        
        # Create multiple concurrent operations
        tasks = []
        for i in range(10):
            task = logger.log_agent_execution(
                f"agent_{i}", f"exec_{i}", "test_action",
                {"iteration": i}, {"result": "success"}, True, 100
            )
            tasks.append(task)
        
        # Execute concurrently
        start_time = time.time()
        await asyncio.gather(*tasks)
        execution_time = time.time() - start_time
        
        # Verify all operations completed
        history = await logger.db.get_execution_history(hours=1)
        assert len(history) >= 10, f"Expected 10 operations, got {len(history)}"
        
        # Verify performance
        assert execution_time < 1.0, f"Concurrent operations took {execution_time:.3f}s"
    
    async def test_error_handling(self, temp_db):
        """
        Test error handling in logging operations.
        
        Verifies errors are handled gracefully without data corruption.
        """
        db_manager, logger, _ = temp_db
        
        # Test with invalid data (should be handled gracefully)
        try:
            await logger.log_agent_execution(
                "", "exec_001", "test_action",  # Empty agent ID
                {"test": "data"}, {"result": "success"}, True, 100
            )
        except Exception as e:
            # Should handle gracefully
            assert "agent_id" in str(e).lower()
        
        # Verify database is still functional
        await logger.log_agent_execution(
            "test_agent", "exec_002", "test_action",
            {"test": "data"}, {"result": "success"}, True, 100
        )
        
        history = await logger.db.get_execution_history(agent_id="test_agent")
        assert len(history) >= 1


class TestProfessionalTradingOrchestrator:
    """Test professional trading orchestrator with state machine"""
    
    @pytest_asyncio.fixture
    async def orchestrator(self):
        """Create isolated orchestrator for testing"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        orchestrator = create_professional_orchestrator()
        
        yield orchestrator
        
        # Cleanup
        os.unlink(db_path)
    
    async def test_state_initialization(self, orchestrator):
        """
        Test state initialization.
        
        Verifies trading state is properly initialized with all required fields.
        """
        state = await orchestrator._initialize_state()
        
        # Verify state structure
        required_fields = [
            "market_data", "portfolio_value", "available_capital", "total_pnl",
            "risk_snapshot", "decision_log", "current_phase", "orchestrator_id", "session_id"
        ]
        
        for field in required_fields:
            assert field in state, f"Missing required field: {field}"
        
        # Verify initial values
        assert state["portfolio_value"] == 100000.0
        assert state["available_capital"] == 100000.0
        assert state["total_pnl"] == 0.0
        assert state["current_phase"] == TradingPhase.INITIALIZING.value
    
    async def test_trading_cycle_execution(self, orchestrator):
        """
        Test complete trading cycle.
        
        Verifies trading cycle completes and transitions to appropriate phase.
        """
        # Run trading cycle
        state = await orchestrator.run_trading_cycle()
        
        # Verify cycle completed
        assert state["current_phase"] in [TradingPhase.MONITORING.value, TradingPhase.ERROR_HANDLING.value]
        assert "last_action" in state
    
    async def test_error_handling(self, orchestrator):
        """
        Test error handling in state machine.
        
        Verifies errors are handled and system recovers properly.
        """
        # Create state with error
        state = await orchestrator._initialize_state()
        state["error_state"] = "Test error"
        
        # Run through error handling node
        result = await orchestrator._error_handling_node(state)
        
        # Verify error was handled
        assert result["current_phase"] == TradingPhase.ERROR_HANDLING.value
        assert result["error_state"] is None  # Should be cleared
        assert result["last_action"] == "error_recovery_completed"
    
    async def test_safety_protocol_enforcement(self, orchestrator):
        """
        Test safety protocol enforcement.
        
        Verifies trading limits are enforced correctly.
        """
        state = await orchestrator._initialize_state()
        
        # Test daily loss limit
        state["current_daily_loss"] = orchestrator.safety.max_daily_loss + 100
        safety_decision = orchestrator.safety.check_trade_safety(
            {"size": 1000, "confidence": 0.8}, state
        )
        assert safety_decision == "emergency_stop"
        assert orchestrator.safety.emergency_stop == True
        
        # Reset for next test
        orchestrator.safety.emergency_stop = False
        
        # Test position size limit
        safety_decision = orchestrator.safety.check_trade_safety(
            {"size": orchestrator.safety.max_position_size + 1000, "confidence": 0.8}, state
        )
        assert safety_decision == "reject"
        
        # Test confidence threshold
        safety_decision = orchestrator.safety.check_trade_safety(
            {"size": 1000, "confidence": 0.5}, state  # Below 0.7 threshold
        )
        assert safety_decision == "reject"


class TestIntegration:
    """Integration tests for the complete system"""
    
    async def test_core_system_integration(self):
        """
        Test integration between core components.
        
        Verifies logging and orchestrator work together correctly.
        """
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            # Initialize systems
            db_manager, logger, test_manager = create_stateful_logging_system(db_path)
            orchestrator = create_professional_orchestrator()
            
            # Test orchestrator execution
            state = await orchestrator.run_trading_cycle()
            
            # Test logging integration
            await logger.log_agent_execution(
                "orchestrator", "cycle_001", "run_cycle",
                {}, {"result": "success"}, True, 200
            )
            
            # Verify integration worked
            assert state["current_phase"] in [TradingPhase.MONITORING.value, TradingPhase.ERROR_HANDLING.value]
            
            history = await logger.db.get_execution_history(agent_id="orchestrator")
            assert len(history) >= 1
            assert history[0]["success"] == True
            
        finally:
            os.unlink(db_path)
    
    async def test_system_observability(self):
        """
        Test system observability and monitoring.
        
        Verifies all components provide adequate observability.
        """
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            db_manager, logger, test_manager = create_stateful_logging_system(db_path)
            
            # Perform various operations
            await logger.log_agent_execution("agent_1", "exec_1", "action1", {}, {"result": "success"}, True, 100)
            await logger.log_agent_execution("agent_2", "exec_2", "action2", {}, {"result": "error"}, False, 200)
            await logger.log_performance_evaluation("agent_1", {"success_rate": 0.9})
            
            # Check system observability
            summary = await db_manager.get_system_summary()
            
            # Verify observability data is available
            assert "agent_status_counts" in summary
            assert "execution_stats_24h" in summary
            assert "performance_averages_24h" in summary
            
            # Verify specific metrics
            assert summary["execution_stats_24h"]["total_executions"] >= 2
            assert summary["execution_stats_24h"]["successful_executions"] >= 1
            
        finally:
            os.unlink(db_path)
    
    async def test_error_recovery_workflow(self):
        """
        Test complete error recovery workflow.
        
        Verifies system can recover from errors and continue operation.
        """
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            db_manager, logger, test_manager = create_stateful_logging_system(db_path)
            orchestrator = create_professional_orchestrator()
            
            # Simulate error condition
            state = await orchestrator._initialize_state()
            state["error_state"] = "Database connection failed"
            
            # Log the error
            await logger.log_agent_event(
                "system", EventType.SYSTEM_EVENT, LogLevel.ERROR, AgentStatus.ERROR,
                "Database connection failed",
                {"error_type": "connection_error", "retry_count": 3}
            )
            
            # Run error recovery
            recovered_state = await orchestrator._error_handling_node(state)
            
            # Verify recovery
            assert recovered_state["current_phase"] == TradingPhase.ERROR_HANDLING.value
            assert recovered_state["error_state"] is None
            
            # Log recovery
            await logger.log_agent_event(
                "system", EventType.SYSTEM_EVENT, LogLevel.INFO, AgentStatus.ACTIVE,
                "Error recovery completed",
                {"recovery_time": datetime.now().isoformat()}
            )
            
            # Verify system can continue
            next_state = await orchestrator.run_trading_cycle()
            assert next_state["current_phase"] in [TradingPhase.MONITORING.value, TradingPhase.ERROR_HANDLING.value]
            
        finally:
            os.unlink(db_path)


class TestPerformance:
    """Performance and load tests"""
    
    async def test_execution_performance(self):
        """
        Test individual operation performance.
        
        Verifies operations complete within expected time limits.
        """
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            _, logger, _ = create_stateful_logging_system(db_path)
            
            start_time = time.time()
            
            # Perform operation
            await logger.log_agent_execution(
                "perf_test_agent", "perf_exec_001", "performance_test",
                {"test": "data"}, {"result": "success"}, True, 100
            )
            
            execution_time = time.time() - start_time
            
            # Assert performance requirement
            assert execution_time < 0.1, f"Operation took {execution_time:.3f}s, expected < 0.1s"
            
        finally:
            os.unlink(db_path)
    
    async def test_database_query_performance(self):
        """
        Test database query performance.
        
        Verifies database queries perform efficiently.
        """
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            db_manager, logger, test_manager = create_stateful_logging_system(db_path)
            
            # Insert test data
            for i in range(100):
                await logger.log_agent_execution(
                    f"agent_{i}", f"exec_{i}", "test_action",
                    {"iteration": i}, {"result": "success"}, True, 100
                )
            
            # Test query performance
            start_time = time.time()
            history = await logger.db.get_execution_history(hours=24)
            query_time = time.time() - start_time
            
            # Verify query efficiency
            assert len(history) >= 100
            assert query_time < 0.5, f"Query took {query_time:.3f}s, expected < 0.5s"
            
        finally:
            os.unlink(db_path)


# Test execution configuration
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
