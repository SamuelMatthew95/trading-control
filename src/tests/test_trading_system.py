"""
Comprehensive Test Suite for Trading System
Stateful testing with database persistence and meaningful test scenarios
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List
import tempfile
import os

# Import all systems to test
from stateful_logging_system import (
    DatabaseManager, StatefulLogger, TestDatabaseManager,
    LogLevel, EventType, AgentStatus, PerformanceMetric,
    create_stateful_logging_system
)
from deterministic_trading_system import (
    DeterministicTradingSystem, SelfImprovingAgent,
    AgentMetrics, LearningSignal, AgentCommunicationProtocol,
    create_deterministic_trading_system
)
from intelligent_learning_system import (
    CollaborativeLearningDatabase, IntelligentLearningManager,
    DynamicTeamManager, MistakePattern, ExpertiseArea,
    create_intelligent_learning_system
)
from professional_trading_orchestrator import (
    SupervisorOrchestrator, TradingState, TradingPhase,
    create_professional_orchestrator
)


class TestStatefulLoggingSystem:
    """Test stateful logging system with database persistence"""
    
    @pytest.fixture
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
        _, logger, test_manager = await temp_db
        
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
        history = await logger.db.get_execution_history(agent_id="agent_001", limit=1)
        assert len(history) == 1
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
        _, logger, test_manager = await temp_db
        
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
        _, logger, test_manager = await temp_db
        
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
        _, logger, test_manager = await temp_db
        
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
        
        metric_values = {m["metric_type"]: m["metric_value"] for m in recorded_metrics}
        assert metric_values["success_rate"] == 0.92
        assert metric_values["execution_time"] == 125.5
    
    @pytest.mark.asyncio
    async def test_system_summary(self, temp_db):
        """Test system summary generation"""
        _, logger, test_manager = await temp_db
        
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


class TestDeterministicTradingSystem:
    """Test deterministic trading system"""
    
    @pytest.fixture
    async def trading_system(self):
        """Create trading system for testing"""
        system = create_deterministic_trading_system()
        yield system
        # Cleanup handled by system itself
    
    @pytest.mark.asyncio
    async def test_agent_registration(self, trading_system):
        """Test agent registration"""
        # Register test agent
        test_agent = TestAgent("test_agent_001")
        trading_system.register_agent(test_agent)
        
        assert "test_agent_001" in trading_system.agents
        assert len(trading_system.agents) == 1
    
    @pytest.mark.asyncio
    async def test_agent_execution_with_learning(self, trading_system):
        """Test agent execution with learning"""
        # Register test agent
        test_agent = TestAgent("test_agent_001")
        trading_system.register_agent(test_agent)
        
        # Execute task
        result = await trading_system.execute_agent_task(
            "test_agent_001", "test_action", {"test_param": "value"}
        )
        
        assert result["success"] == True
        assert "execution_id" in result
        assert "execution_time_ms" in result
        assert "agent_rank" in result
        
        # Verify learning signal was created
        assert len(trading_system.learning_manager.learning_signals) > 0
    
    @pytest.mark.asyncio
    async def test_agent_execution_failure_handling(self, trading_system):
        """Test agent execution failure handling"""
        # Register test agent that fails
        failing_agent = FailingTestAgent("failing_agent_001")
        trading_system.register_agent(failing_agent)
        
        # Execute task that should fail
        result = await trading_system.execute_agent_task(
            "failing_agent_001", "failing_action", {"test_param": "value"}
        )
        
        assert result["success"] == False
        assert "error" in result
        assert "execution_id" in result
        
        # Verify learning signal was created for failure
        failure_signals = [s for s in trading_system.learning_manager.learning_signals if not s.success]
        assert len(failure_signals) > 0
    
    @pytest.mark.asyncio
    async def test_agent_communication(self, trading_system):
        """Test agent communication"""
        # Register test agents
        agent1 = TestAgent("agent_001")
        agent2 = TestAgent("agent_002")
        trading_system.register_agent(agent1)
        trading_system.register_agent(agent2)
        
        # Send message from agent1 to agent2
        from deterministic_trading_system import AgentCommunicationProtocol
        protocol = AgentCommunicationProtocol()
        
        message = AgentCommunicationProtocol.Message.create(
            "agent_001", "agent_002", "test_message",
            {"content": "test data"}, priority=3
        )
        
        protocol.send_message(message)
        
        # Process communications
        results = await trading_system.process_agent_communications()
        
        assert len(results) == 1
        assert results[0]["success"] == True
    
    @pytest.mark.asyncio
    async def test_agent_ranking_system(self, trading_system):
        """Test agent ranking system"""
        # Register multiple test agents
        agents = [
            TestAgent("agent_001"),
            TestAgent("agent_002"),
            TestAgent("agent_003")
        ]
        
        for agent in agents:
            trading_system.register_agent(agent)
        
        # Execute multiple tasks to generate ranking data
        for agent_id in ["agent_001", "agent_002", "agent_003"]:
            for i in range(5):
                await trading_system.execute_agent_task(
                    agent_id, "test_action", {"iteration": i}
                )
        
        # Get top agents
        top_agents = trading_system.ranking_system.get_top_agents(3)
        assert len(top_agents) == 3
        assert all("agent_id" in agent for agent in top_agents)
        assert all("ranking_score" in agent for agent in top_agents)
        
        # Verify ranking scores are calculated
        for agent in top_agents:
            assert 0 <= agent["ranking_score"] <= 1.0


class TestIntelligentLearningSystem:
    """Test intelligent learning system"""
    
    @pytest.fixture
    async def learning_system(self):
        """Create learning system for testing"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        database = CollaborativeLearningDatabase()
        learning_manager = IntelligentLearningManager(database)
        team_manager = DynamicTeamManager(learning_manager)
        
        yield learning_manager, team_manager, database
        
        # Cleanup
        os.unlink(db_path)
    
    @pytest.mark.asyncio
    async def test_mistake_analysis(self, learning_system):
        """Test mistake analysis"""
        learning_manager, _, database = learning_system
        
        # Analyze mistake
        analysis = await learning_manager.analyze_mistake(
            execution_id="test_exec_001",
            agent_id="test_agent_001",
            action="analyze_market",
            input_data={"symbol": "AAPL"},
            error="Data interpretation failed: invalid price format",
            execution_context={"financial_impact": 500, "system_load": 0.7}
        )
        
        # Verify analysis structure
        assert analysis.execution_id == "test_exec_001"
        assert analysis.agent_id == "test_agent_001"
        assert analysis.mistake_pattern == MistakePattern.DATA_INTERPRETATION_ERROR
        assert analysis.severity in ["critical", "major", "minor"]
        assert len(analysis.learning_insights) > 0
        assert len(analysis.prevention_strategies) > 0
        
        # Verify analysis was stored
        assert analysis.execution_id in database.mistake_analyses
    
    @pytest.mark.asyncio
    async def test_success_pattern_analysis(self, learning_system):
        """Test success pattern analysis"""
        learning_manager, _, database = learning_system
        
        # Analyze success
        pattern = await learning_manager.analyze_success(
            execution_id="test_exec_002",
            agent_id="test_agent_002",
            action="assess_risk",
            input_data={"trade_size": 1000},
            result={"risk_score": 0.3, "approved": True},
            execution_context={"execution_time_ms": 200}
        )
        
        # Verify pattern structure
        assert pattern.execution_id == "test_exec_002"
        assert pattern.agent_id == "test_agent_002"
        assert len(pattern.success_factors) > 0
        assert len(pattern.replicable_strategies) > 0
        assert len(pattern.expertise_demonstrated) > 0
        
        # Verify pattern was stored
        assert pattern.execution_id in database.success_patterns
    
    @pytest.mark.asyncio
    async def test_learning_recommendations(self, learning_system):
        """Test learning recommendations"""
        learning_manager, _, database = learning_system
        
        # Create some test data first
        await learning_manager.analyze_mistake(
            "test_exec_003", "test_agent_003", "analyze_market",
            {"symbol": "TSLA"}, "Risk assessment failed", {}
        )
        
        # Get recommendations
        recommendations = await learning_manager.get_learning_recommendations(
            "test_agent_003", MistakePattern.RISK_MISJUDGMENT
        )
        
        # Verify recommendations structure
        assert "mistake_pattern" in recommendations
        assert "learning_strategies" in recommendations
        assert "recommended_collaborations" in recommendations
        assert "expert_agents_available" in recommendations
        assert len(recommendations["learning_strategies"]) > 0
    
    @pytest.mark.asyncio
    async def test_team_formation(self, learning_system):
        """Test team formation"""
        learning_manager, _, database = learning_system
        
        # Create some agents with expertise
        database.agent_expertise["expert_agent_001"] = AgentExpertise(
            agent_id="expert_agent_001",
            expertise_areas={ExpertiseArea.RISK_MANAGEMENT: 0.9},
            learning_history=[], teaching_history=[],
            collaboration_success={}, mistake_patterns={},
            last_updated=datetime.now().isoformat()
        )
        
        database.agent_expertise["expert_agent_002"] = AgentExpertise(
            agent_id="expert_agent_002",
            expertise_areas={ExpertiseArea.DATA_VALIDATION: 0.8},
            learning_history=[], teaching_history=[],
            collaboration_success={}, mistake_patterns={},
            last_updated=datetime.now().isoformat()
        )
        
        # Form team
        team = await learning_manager.form_learning_team(
            "learner_agent_001",
            "risk_improvement",
            [ExpertiseArea.RISK_MANAGEMENT, ExpertiseArea.DATA_VALIDATION]
        )
        
        # Verify team structure
        assert team.team_id is not None
        assert "learner_agent_001" in team.selected_agents
        assert len(team.selected_agents) >= 2  # Should include experts
        assert 0 <= team.confidence_score <= 1.0
        assert team.formation_strategy == "expertise_gap_filling"
    
    @pytest.mark.asyncio
    async def test_collaborative_learning(self, learning_system):
        """Test collaborative learning"""
        learning_manager, _, database = learning_system
        
        # Create test team
        team = TeamFormation(
            team_id="test_team_001",
            task_type="test_learning",
            required_expertise=[ExpertiseArea.MARKET_ANALYSIS],
            selected_agents=["agent_001", "agent_002"],
            formation_strategy="test",
            confidence_score=0.8,
            historical_performance=0.85,
            timestamp=datetime.now().isoformat()
        )
        
        # Facilitate collaborative learning
        collaboration = await learning_manager.facilitate_collaborative_learning(
            team, {"task": "test_collaboration"}
        )
        
        # Verify collaboration structure
        assert "collaboration_id" in collaboration
        assert "overall_success" in collaboration
        assert "knowledge_sharing" in collaboration
        assert "mistake_analysis" in collaboration
        assert "strategy_development" in collaboration
        assert 0 <= collaboration["overall_success"] <= 1.0
    
    @pytest.mark.asyncio
    async def test_performance_evaluation(self, learning_system):
        """Test performance evaluation"""
        learning_manager, team_manager, database = learning_system
        
        # Create test agent with history
        database.agent_expertise["test_agent_001"] = AgentExpertise(
            agent_id="test_agent_001",
            expertise_areas={
                ExpertiseArea.MARKET_ANALYSIS: 0.8,
                ExpertiseArea.RISK_MANAGEMENT: 0.6
            },
            learning_history=["exec_001", "exec_002"],
            teaching_history=["exec_003"],
            collaboration_success={"agent_002": 0.9},
            mistake_patterns={MistakePattern.DATA_INTERPRETATION_ERROR: 1},
            last_updated=datetime.now().isoformat()
        )
        
        # Create some learning signals
        for i in range(10):
            signal = LearningSignal(
                execution_id=f"exec_{i}",
                agent_id="test_agent_001",
                action="test_action",
                input_hash=f"hash_{i}",
                output_hash=f"output_{i}",
                success=i % 3 != 0,  # 2/3 success rate
                reward=1.0 if i % 3 != 0 else -1.0,
                execution_time_ms=100 + i * 10,
                error_type=None if i % 3 != 0 else "test_error",
                timestamp=datetime.now().isoformat()
            )
            database.learning_signals.append(signal)
        
        # Evaluate performance
        evaluation = await learning_manager.evaluate_agent_performance_trend(
            "test_agent_001", days=30
        )
        
        # Verify evaluation structure
        assert evaluation["agent_id"] == "test_agent_001"
        assert "success_rate" in evaluation
        assert "recommendation" in evaluation
        assert "expertise_growth" in evaluation
        assert evaluation["recommendation"] in ["promote", "maintain", "improving", "let_go"]
    
    @pytest.mark.asyncio
    async def test_team_management(self, learning_system):
        """Test dynamic team management"""
        learning_manager, team_manager, database = learning_system
        
        # Create test agents with different performance levels
        high_performer = AgentExpertise(
            agent_id="high_performer",
            expertise_areas={ExpertiseArea.MARKET_ANALYSIS: 0.95},
            learning_history=[], teaching_history=[],
            collaboration_success={}, mistake_patterns={},
            last_updated=datetime.now().isoformat()
        )
        
        low_performer = AgentExpertise(
            agent_id="low_performer",
            expertise_areas={ExpertiseArea.MARKET_ANALYSIS: 0.3},
            learning_history=[], teaching_history=[],
            collaboration_success={}, mistake_patterns={},
            last_updated=datetime.now().isoformat()
        )
        
        database.agent_expertise["high_performer"] = high_performer
        database.agent_expertise["low_performer"] = low_performer
        
        # Evaluate and adjust teams
        results = await team_manager.evaluate_and_adjust_teams()
        
        # Verify evaluation results
        assert "evaluations_completed" in results
        assert "agents_retired" in results
        assert "agents_promoted" in results
        assert results["evaluations_completed"] >= 2


class TestProfessionalTradingOrchestrator:
    """Test professional trading orchestrator"""
    
    @pytest.fixture
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
        assert len(state["decision_log"]) > 0
        
        # Verify state was persisted
        loaded_state = await orchestrator.state_storage.load_state()
        assert loaded_state is not None
        assert loaded_state["orchestrator_id"] == state["orchestrator_id"]
    
    @pytest.mark.asyncio
    async def test_safety_protocol_enforcement(self, orchestrator):
        """Test safety protocol enforcement"""
        # Test daily loss limit
        state = await orchestrator._initialize_state()
        state["current_daily_loss"] = orchestrator.safety.max_daily_loss + 100
        
        safety_decision = orchestrator.safety.check_trade_safety(
            {"size": 1000, "confidence": 0.8}, state
        )
        
        assert safety_decision == "emergency_stop"
        assert orchestrator.safety.emergency_stop == True
    
    @pytest.mark.asyncio
    async def test_position_size_limit(self, orchestrator):
        """Test position size limit enforcement"""
        state = await orchestrator._initialize_state()
        
        # Test position size limit
        safety_decision = orchestrator.safety.check_trade_safety(
            {"size": orchestrator.safety.max_position_size + 1000, "confidence": 0.8}, state
        )
        
        assert safety_decision == "reject"
    
    @pytest.mark.asyncio
    async def test_confidence_threshold(self, orchestrator):
        """Test confidence threshold enforcement"""
        state = await orchestrator._initialize_state()
        
        # Test confidence threshold
        safety_decision = orchestrator.safety.check_trade_safety(
            {"size": 1000, "confidence": 0.5}, state  # Below 0.7 threshold
        )
        
        assert safety_decision == "reject"
    
    @pytest.mark.asyncio
    async def test_error_handling(self, orchestrator):
        """Test error handling in state machine"""
        # Create state with error
        state = await orchestrator._initialize_state()
        state["error_state"] = "Test error"
        
        # Run through error handling node
        result = await orchestrator._error_handling_node(state)
        
        assert result["current_phase"] == TradingPhase.ERROR_HANDLING.value
        assert result["error_state"] is None  # Should be cleared
        assert result["last_action"] == "error_recovery_completed"


class TestIntegration:
    """Integration tests for the complete system"""
    
    @pytest.mark.asyncio
    async def test_complete_trading_workflow(self):
        """Test complete trading workflow with all systems"""
        # Create all systems
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            # Initialize systems
            db_manager, logger, test_manager = create_stateful_logging_system(db_path)
            trading_system = create_deterministic_trading_system()
            learning_manager, team_manager, database = create_intelligent_learning_system()
            orchestrator = create_professional_orchestrator()
            
            # Register agents with trading system
            test_agent = TestAgent("integration_agent_001")
            trading_system.register_agent(test_agent)
            
            # Execute trading cycle
            trading_state = await orchestrator.run_trading_cycle()
            
            # Execute agent task
            agent_result = await trading_system.execute_agent_task(
                "integration_agent_001", "analyze_market", {"symbol": "AAPL"}
            )
            
            # Log execution
            await logger.log_agent_execution(
                "integration_agent_001",
                agent_result["execution_id"],
                "analyze_market",
                {"symbol": "AAPL"},
                agent_result.get("result"),
                agent_result["success"],
                agent_result.get("execution_time_ms", 0)
            )
            
            # Analyze performance if needed
            if not agent_result["success"]:
                mistake_analysis = await learning_manager.analyze_mistake(
                    agent_result["execution_id"],
                    "integration_agent_001",
                    "analyze_market",
                    {"symbol": "AAPL"},
                    agent_result.get("error", "Unknown error"),
                    {}
                )
                
                await logger.log_mistake_analysis(
                    "integration_agent_001",
                    agent_result["execution_id"],
                    mistake_analysis.mistake_pattern.value,
                    {
                        "root_cause": mistake_analysis.root_cause,
                        "severity": mistake_analysis.severity
                    }
                )
            
            # Verify system state
            system_summary = await logger.db.get_system_summary()
            
            # Assertions
            assert trading_state["current_phase"] in [TradingPhase.MONITORING.value, TradingPhase.ERROR_HANDLING.value]
            assert agent_result["execution_id"] is not None
            assert system_summary["execution_stats_24h"]["total_executions"] >= 1
            
        finally:
            # Cleanup
            os.unlink(db_path)
    
    @pytest.mark.asyncio
    async def test_learning_integration(self):
        """Test learning system integration with trading system"""
        # Create systems
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            db_manager, logger, test_manager = create_stateful_logging_system(db_path)
            trading_system = create_deterministic_trading_system()
            learning_manager, team_manager, database = create_intelligent_learning_system()
            
            # Create agent that makes mistakes
            failing_agent = FailingTestAgent("learning_agent_001")
            trading_system.register_agent(failing_agent)
            
            # Execute multiple failing tasks
            execution_ids = []
            for i in range(3):
                result = await trading_system.execute_agent_task(
                    "learning_agent_001", "failing_action", {"iteration": i}
                )
                execution_ids.append(result["execution_id"])
                
                # Log execution
                await logger.log_agent_execution(
                    "learning_agent_001",
                    result["execution_id"],
                    "failing_action",
                    {"iteration": i},
                    None,
                    False,
                    result.get("execution_time_ms", 0),
                    result.get("error")
                )
            
            # Analyze mistakes
            for exec_id in execution_ids:
                mistake_analysis = await learning_manager.analyze_mistake(
                    exec_id, "learning_agent_001", "failing_action",
                    {"iteration": 0}, "Intentional test failure", {}
                )
                
                # Get learning recommendations
                recommendations = await learning_manager.get_learning_recommendations(
                    "learning_agent_001", mistake_analysis.mistake_pattern
                )
                
                # Verify recommendations exist
                assert len(recommendations["learning_strategies"]) > 0
            
            # Verify learning progress
            learning_progress = database.get_agent_learning_progress("learning_agent_001")
            assert learning_progress["total_learning_experiences"] >= 3
            
        finally:
            # Cleanup
            os.unlink(db_path)


# Test Helper Classes

class TestAgent(SelfImprovingAgent):
    """Test agent for deterministic trading system tests"""
    
    def __init__(self, agent_id: str):
        # Create minimal dependencies for testing
        from deterministic_trading_system import AgentCommunicationProtocol, LearningManager, AgentRankingSystem
        self.agent_id = agent_id
        self.communication_protocol = AgentCommunicationProtocol()
        self.learning_manager = LearningManager()
        self.ranking_system = AgentRankingSystem()
        self.execution_count = 0
    
    async def _execute_action(self, action: str, input_data: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
        """Execute test action"""
        await asyncio.sleep(0.01)  # Simulate work
        return {
            "action": action,
            "input_received": input_data,
            "result": "test_success",
            "timestamp": datetime.now().isoformat()
        }


class FailingTestAgent(SelfImprovingAgent):
    """Test agent that always fails for testing error handling"""
    
    def __init__(self, agent_id: str):
        from deterministic_trading_system import AgentCommunicationProtocol, LearningManager, AgentRankingSystem
        self.agent_id = agent_id
        self.communication_protocol = AgentCommunicationProtocol()
        self.learning_manager = LearningManager()
        self.ranking_system = AgentRankingSystem()
        self.execution_count = 0
    
    async def _execute_action(self, action: str, input_data: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
        """Always fail for testing"""
        await asyncio.sleep(0.01)
        raise ValueError("Intentional test failure")


# Test Configuration

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Test Execution

if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
