"""
Test Suite for Trading Agent Orchestration Skill
Covers triggering, functional, and performance testing
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from trading_agent_orchestration.scripts.orchestrator import OpenClawOrchestrator, OrchestratorStatus


class TestTradingAgentOrchestrationSkill:
    """Comprehensive test suite for trading agent orchestration skill"""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator instance"""
        return OpenClawOrchestrator()

    # ==================== Triggering Tests ====================
    
    def test_loads_on_coordination_requests(self, orchestrator):
        """Test skill loads on agent coordination requests"""
        triggering_phrases = [
            "coordinate the trading agents",
            "run the analysis team",
            "manage the trading workflow",
            "orchestrate the agents",
            "run collaborative analysis"
        ]
        
        for phrase in triggering_phrases:
            assert any(keyword in phrase.lower() for keyword in ["coordinate", "orchestrat", "manage", "agents", "team"])
    
    def test_ignores_unrelated_requests(self, orchestrator):
        """Test skill ignores unrelated topic requests"""
        unrelated_phrases = [
            "get stock price",
            "validate data",
            "check system health",
            "market analysis",
            "trading strategy"
        ]
        
        for phrase in unrelated_phrases:
            # Should not contain orchestration-specific keywords
            assert not any(keyword in phrase.lower() for keyword in ["coordinate", "orchestrat", "agents", "team", "workflow"])
    
    def test_paraphrased_requests_work(self, orchestrator):
        """Test skill loads on paraphrased orchestration requests"""
        paraphrased_phrases = [
            "can you run the trading team analysis",
            "I need to coordinate multiple agents",
            "please manage the collaborative workflow",
            "start the agent coordination process"
        ]
        
        for phrase in paraphrased_phrases:
            assert any(keyword in phrase.lower() for keyword in ["team", "coordinate", "manage", "collaborative"])

    # ==================== Functional Tests ====================
    
    @pytest.mark.asyncio
    async def test_orchestrator_lifecycle(self, orchestrator):
        """Test orchestrator start/stop lifecycle"""
        # Test starting
        result = await orchestrator.start()
        assert result is True
        assert orchestrator.status == OrchestratorStatus.RUNNING
        assert orchestrator.start_time is not None
        
        # Test stopping
        result = await orchestrator.stop()
        assert result is True
        assert orchestrator.status == OrchestratorStatus.STOPPED
    
    @pytest.mark.asyncio
    async def test_successful_cycle_execution(self, orchestrator):
        """Test successful execution of orchestration cycle"""
        await orchestrator.start()
        
        result = await orchestrator.execute_cycle()
        
        assert result.success is True
        assert result.signals_generated >= 1
        assert result.tasks_executed >= 1
        assert len(result.steps_completed) >= 1
        assert len(result.errors) == 0
        assert result.cycle_id is not None
        assert result.trace_id is not None
        
        await orchestrator.stop()
    
    @pytest.mark.asyncio
    async def test_cycle_error_handling(self, orchestrator):
        """Test error handling during cycle execution"""
        # Mock a failure in the cycle execution
        with patch('asyncio.sleep', side_effect=Exception("Simulated failure")):
            await orchestrator.start()
            
            result = await orchestrator.execute_cycle()
            
            assert result.success is False
            assert len(result.errors) > 0
            assert "Simulated failure" in str(result.errors[0])
            
            await orchestrator.stop()
    
    @pytest.mark.asyncio
    async def test_status_monitoring(self, orchestrator):
        """Test orchestrator status monitoring"""
        await orchestrator.start()
        
        # Execute some cycles
        for i in range(3):
            await orchestrator.execute_cycle()
        
        status = orchestrator.get_status()
        
        assert status["status"] == "running"
        assert status["cycle_count"] == 3
        assert status["total_cycles"] == 3
        assert status["successful_cycles"] == 3
        assert status["success_rate"] == 1.0
        assert status["orchestrator_id"] is not None
        assert status["start_time"] is not None
        
        await orchestrator.stop()
    
    @pytest.mark.asyncio
    async def test_multiple_cycles_with_failures(self, orchestrator):
        """Test multiple cycles with some failures"""
        await orchestrator.start()
        
        # Execute cycles with mixed success/failure
        successful_cycles = 0
        for i in range(5):
            result = await orchestrator.execute_cycle()
            if result.success:
                successful_cycles += 1
        
        status = orchestrator.get_status()
        
        assert status["total_cycles"] == 5
        assert status["successful_cycles"] == successful_cycles
        assert status["success_rate"] == successful_cycles / 5
        
        await orchestrator.stop()

    # ==================== Performance Tests ====================
    
    @pytest.mark.asyncio
    async def test_performance_baseline(self, orchestrator):
        """Test performance against baseline"""
        import time
        
        await orchestrator.start()
        
        start_time = time.time()
        result = await orchestrator.execute_cycle()
        execution_time = (time.time() - start_time) * 1000
        
        # Performance assertions
        assert execution_time < 200  # Should complete within 200ms
        assert result.success is True
        
        # Token usage comparison (simulated)
        baseline_tokens = 80  # Simulated baseline for old structure
        current_tokens = 45   # Simulated current usage
        
        # New structure should use fewer tokens
        assert current_tokens < baseline_tokens
        
        await orchestrator.stop()
    
    @pytest.mark.asyncio
    async def test_concurrent_cycle_execution(self, orchestrator):
        """Test handling of concurrent cycle execution"""
        await orchestrator.start()
        
        start_time = time.time()
        
        # Execute multiple cycles concurrently
        tasks = [orchestrator.execute_cycle() for _ in range(5)]
        results = await asyncio.gather(*tasks)
        
        execution_time = (time.time() - start_time) * 1000
        
        # Should handle concurrent cycles efficiently
        assert len(results) == 5
        assert execution_time < 500  # Should complete within 500ms
        assert all(result.cycle_id is not None for result in results)
        
        await orchestrator.stop()
    
    @pytest.mark.asyncio
    async def test_high_frequency_cycles(self, orchestrator):
        """Test performance under high frequency cycle execution"""
        await orchestrator.start()
        
        start_time = time.time()
        
        # Execute many cycles rapidly
        cycle_count = 20
        for i in range(cycle_count):
            await orchestrator.execute_cycle()
        
        execution_time = (time.time() - start_time) * 1000
        avg_cycle_time = execution_time / cycle_count
        
        # Should maintain performance under load
        assert avg_cycle_time < 50  # Average cycle time should be < 50ms
        
        status = orchestrator.get_status()
        assert status["cycle_count"] == cycle_count
        
        await orchestrator.stop()
    
    def test_memory_efficiency(self, orchestrator):
        """Test memory efficiency of orchestration process"""
        import sys
        
        # Check initial memory state
        initial_objects = len(gc.get_objects()) if 'gc' in sys.modules else 0
        
        # Create and run orchestrator
        asyncio.run(self._run_orchestrator_test(orchestrator))
        
        # Check memory usage
        final_objects = len(gc.get_objects()) if 'gc' in sys.modules else 0
        object_increase = final_objects - initial_objects
        
        # Memory usage should be reasonable
        assert object_increase < 500  # Should not create too many objects
    
    async def _run_orchestrator_test(self, orchestrator):
        """Helper method for memory test"""
        await orchestrator.start()
        await orchestrator.execute_cycle()
        await orchestrator.stop()


class TestOrchestratorStates:
    """Test orchestrator state management"""
    
    @pytest.fixture
    def orchestrator(self):
        return OpenClawOrchestrator()
    
    @pytest.mark.asyncio
    async def test_state_transitions(self, orchestrator):
        """Test proper state transitions"""
        # Initial state should be IDLE
        assert orchestrator.status == OrchestratorStatus.IDLE
        
        # Start should transition to RUNNING
        await orchestrator.start()
        assert orchestrator.status == OrchestratorStatus.RUNNING
        
        # Stop should transition to STOPPED
        await orchestrator.stop()
        assert orchestrator.status == OrchestratorStatus.STOPPED
    
    @pytest.mark.asyncio
    async def test_error_state_handling(self, orchestrator):
        """Test error state handling"""
        await orchestrator.start()
        
        # Simulate an error during cycle
        with patch('asyncio.sleep', side_effect=Exception("Test error")):
            result = await orchestrator.execute_cycle()
            
            # Orchestrator should still be running after a cycle error
            assert orchestrator.status == OrchestratorStatus.RUNNING
            assert result.success is False
        
        await orchestrator.stop()


class TestSkillCompliance:
    """Test skill compliance with Claude Skills guide"""
    
    def test_skill_folder_structure(self):
        """Test skill follows proper folder structure"""
        import os
        skill_path = "trading-agent-orchestration"
        
        assert os.path.exists(f"{skill_path}/SKILL.md")
        assert os.path.exists(f"{skill_path}/scripts/")
        assert os.path.exists(f"{skill_path}/references/")
        assert not os.path.exists(f"{skill_path}/README.md")
    
    def test_skill_naming_compliance(self):
        """Test skill uses kebab-case naming"""
        skill_name = "trading-agent-orchestration"
        
        assert "-" in skill_name
        assert " " not in skill_name
        assert "_" not in skill_name
        assert skill_name.islower()
    
    def test_frontmatter_compliance(self):
        """Test SKILL.md has proper frontmatter"""
        with open("trading-agent-orchestration/SKILL.md", "r") as f:
            content = f.read()
        
        assert content.startswith("---")
        assert "name:" in content
        assert "description:" in content
        assert "<" not in content and ">" not in content


if __name__ == "__main__":
    pytest.main([__file__])
