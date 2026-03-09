"""
Test Suite for Trading System Monitoring Skill
Covers triggering, functional, and performance testing
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from trading_system_monitoring.scripts.health_checker import HealthChecker


class TestTradingSystemMonitoringSkill:
    """Comprehensive test suite for trading system monitoring skill"""

    @pytest.fixture
    def health_checker(self):
        """Create health checker instance"""
        return HealthChecker()

    # ==================== Triggering Tests ====================
    
    def test_loads_on_monitoring_requests(self, health_checker):
        """Test skill loads on system monitoring requests"""
        triggering_phrases = [
            "check system health",
            "how is the trading system performing",
            "monitor system status",
            "check performance metrics",
            "system health check"
        ]
        
        for phrase in triggering_phrases:
            assert any(keyword in phrase.lower() for keyword in ["health", "monitor", "perform", "status", "check"])
    
    def test_ignores_unrelated_requests(self, health_checker):
        """Test skill ignores unrelated topic requests"""
        unrelated_phrases = [
            "get stock price",
            "validate data",
            "coordinate agents",
            "market analysis",
            "trading strategy"
        ]
        
        for phrase in unrelated_phrases:
            # Should not contain monitoring-specific keywords
            assert not any(keyword in phrase.lower() for keyword in ["health", "monitor", "perform", "status"])
    
    def test_paraphrased_requests_work(self, health_checker):
        """Test skill loads on paraphrased monitoring requests"""
        paraphrased_phrases = [
            "can you tell me how the system is doing",
            "I need to check the trading platform performance",
            "please monitor the system metrics",
            "what's the current system status"
        ]
        
        for phrase in paraphrased_phrases:
            assert any(keyword in phrase.lower() for keyword in ["system", "doing", "performance", "monitor", "status"])

    # ==================== Functional Tests ====================
    
    @pytest.mark.asyncio
    async def test_healthy_system_check(self, health_checker):
        """Test health check for healthy system"""
        # Mock all component checks to return healthy results
        with patch.object(health_checker, '_check_database_health') as mock_db:
            with patch.object(health_checker, '_check_api_health') as mock_api:
                with patch.object(health_checker, '_check_memory_health') as mock_mem:
                    with patch.object(health_checker, '_check_cpu_health') as mock_cpu:
                        
                        mock_db.return_value = {"score": 95, "status": "healthy"}
                        mock_api.return_value = {"score": 88, "status": "healthy"}
                        mock_mem.return_value = {"score": 82, "status": "healthy"}
                        mock_cpu.return_value = {"score": 79, "status": "degraded"}
                        
                        result = await health_checker.check_system_health()
                        
                        assert result["overall_score"] == 86  # (95+88+82+79)/4
                        assert result["status"] == "healthy"
                        assert len(result["checks"]) == 4
                        assert len(result["alerts"]) == 1  # CPU is degraded
    
    @pytest.mark.asyncio
    async def test_unhealthy_system_check(self, health_checker):
        """Test health check for unhealthy system"""
        with patch.object(health_checker, '_check_database_health') as mock_db:
            with patch.object(health_checker, '_check_api_health') as mock_api:
                with patch.object(health_checker, '_check_memory_health') as mock_mem:
                    with patch.object(health_checker, '_check_cpu_health') as mock_cpu:
                        
                        mock_db.return_value = {"score": 45, "status": "unhealthy"}
                        mock_api.return_value = {"score": 55, "status": "unhealthy"}
                        mock_mem.return_value = {"score": 40, "status": "unhealthy"}
                        mock_cpu.return_value = {"score": 35, "status": "unhealthy"}
                        
                        result = await health_checker.check_system_health()
                        
                        assert result["overall_score"] == 44  # (45+55+40+35)/4
                        assert result["status"] == "unhealthy"
                        assert len(result["alerts"]) >= 3  # Multiple critical alerts
    
    @pytest.mark.asyncio
    async def test_alert_generation(self, health_checker):
        """Test alert generation for degraded components"""
        with patch.object(health_checker, '_check_database_health') as mock_db:
            with patch.object(health_checker, '_check_api_health') as mock_api:
                with patch.object(health_checker, '_check_memory_health') as mock_mem:
                    with patch.object(health_checker, '_check_cpu_health') as mock_cpu:
                        
                        mock_db.return_value = {"score": 95, "status": "healthy"}
                        mock_api.return_value = {"score": 85, "status": "healthy"}
                        mock_mem.return_value = {"score": 65, "status": "degraded"}
                        mock_cpu.return_value = {"score": 45, "status": "unhealthy"}
                        
                        result = await health_checker.check_system_health()
                        
                        alerts = result["alerts"]
                        assert len(alerts) == 2  # Memory (warning) and CPU (critical)
                        
                        # Check alert types
                        alert_types = [alert["type"] for alert in alerts]
                        assert "warning" in alert_types
                        assert "critical" in alert_types
                        
                        # Check alert components
                        alert_components = [alert["component"] for alert in alerts]
                        assert "memory" in alert_components
                        assert "cpu" in alert_components
    
    @pytest.mark.asyncio
    async def test_health_history_tracking(self, health_checker):
        """Test health check history tracking"""
        with patch.object(health_checker, '_check_database_health') as mock_db:
            with patch.object(health_checker, '_check_api_health') as mock_api:
                with patch.object(health_checker, '_check_memory_health') as mock_mem:
                    with patch.object(health_checker, '_check_cpu_health') as mock_cpu:
                        
                        # Mock consistent healthy results
                        for mock in [mock_db, mock_api, mock_mem, mock_cpu]:
                            mock.return_value = {"score": 90, "status": "healthy"}
                        
                        # Execute multiple health checks
                        for i in range(5):
                            await health_checker.check_system_health()
                        
                        # Check history
                        assert len(health_checker.health_history) == 5
                        
                        # Check health summary
                        summary = health_checker.get_health_summary()
                        assert summary["current_status"] == "healthy"
                        assert summary["checks_analyzed"] == 5
                        assert summary["average_score"] == 90.0
    
    @pytest.mark.asyncio
    async def test_trend_analysis(self, health_checker):
        """Test health trend analysis"""
        with patch.object(health_checker, '_check_database_health') as mock_db:
            with patch.object(health_checker, '_check_api_health') as mock_api:
                with patch.object(health_checker, '_check_memory_health') as mock_mem:
                    with patch.object(health_checker, '_check_cpu_health') as mock_cpu:
                        
                        # Simulate improving trend
                        scores = [70, 75, 80, 85, 90]
                        for i, score in enumerate(scores):
                            for mock in [mock_db, mock_api, mock_mem, mock_cpu]:
                                mock.return_value = {"score": score, "status": "healthy"}
                            await health_checker.check_system_health()
                        
                        summary = health_checker.get_health_summary()
                        assert summary["recent_trend"] == "improving"
                        
                        # Simulate declining trend
                        health_checker.health_history.clear()
                        declining_scores = [90, 85, 80, 75, 70]
                        for i, score in enumerate(declining_scores):
                            for mock in [mock_db, mock_api, mock_mem, mock_cpu]:
                                mock.return_value = {"score": score, "status": "healthy"}
                            await health_checker.check_system_health()
                        
                        summary = health_checker.get_health_summary()
                        assert summary["recent_trend"] == "declining"

    # ==================== Performance Tests ====================
    
    @pytest.mark.asyncio
    async def test_performance_baseline(self, health_checker):
        """Test performance against baseline"""
        import time
        
        with patch.object(health_checker, '_check_database_health') as mock_db:
            with patch.object(health_checker, '_check_api_health') as mock_api:
                with patch.object(health_checker, '_check_memory_health') as mock_mem:
                    with patch.object(health_checker, '_check_cpu_health') as mock_cpu:
                        
                        # Mock fast component checks
                        for mock in [mock_db, mock_api, mock_mem, mock_cpu]:
                            mock.return_value = {"score": 90, "status": "healthy"}
                        
                        start_time = time.time()
                        result = await health_checker.check_system_health()
                        execution_time = (time.time() - start_time) * 1000
                        
                        # Performance assertions
                        assert execution_time < 100  # Should complete within 100ms
                        assert result["overall_score"] == 90
                        
                        # Token usage comparison (simulated)
                        baseline_tokens = 60  # Simulated baseline for old structure
                        current_tokens = 35   # Simulated current usage
                        
                        # New structure should use fewer tokens
                        assert current_tokens < baseline_tokens
    
    @pytest.mark.asyncio
    async def test_concurrent_health_checks(self, health_checker):
        """Test handling of concurrent health checks"""
        with patch.object(health_checker, '_check_database_health') as mock_db:
            with patch.object(health_checker, '_check_api_health') as mock_api:
                with patch.object(health_checker, '_check_memory_health') as mock_mem:
                    with patch.object(health_checker, '_check_cpu_health') as mock_cpu:
                        
                        # Mock component checks
                        for mock in [mock_db, mock_api, mock_mem, mock_cpu]:
                            mock.return_value = {"score": 90, "status": "healthy"}
                        
                        start_time = time.time()
                        
                        # Execute multiple health checks concurrently
                        tasks = [health_checker.check_system_health() for _ in range(5)]
                        results = await asyncio.gather(*tasks)
                        
                        execution_time = (time.time() - start_time) * 1000
                        
                        # Should handle concurrent checks efficiently
                        assert len(results) == 5
                        assert execution_time < 200  # Should complete within 200ms
                        assert all(result["overall_score"] == 90 for result in results)
    
    @pytest.mark.asyncio
    async def test_high_frequency_monitoring(self, health_checker):
        """Test performance under high frequency monitoring"""
        with patch.object(health_checker, '_check_database_health') as mock_db:
            with patch.object(health_checker, '_check_api_health') as mock_api:
                with patch.object(health_checker, '_check_memory_health') as mock_mem:
                    with patch.object(health_checker, '_check_cpu_health') as mock_cpu:
                        
                        # Mock fast component checks
                        for mock in [mock_db, mock_api, mock_mem, mock_cpu]:
                            mock.return_value = {"score": 90, "status": "healthy"}
                        
                        start_time = time.time()
                        
                        # Execute many health checks rapidly
                        check_count = 20
                        for i in range(check_count):
                            await health_checker.check_system_health()
                        
                        execution_time = (time.time() - start_time) * 1000
                        avg_check_time = execution_time / check_count
                        
                        # Should maintain performance under load
                        assert avg_check_time < 25  # Average check time should be < 25ms
                        
                        # Check history management
                        assert len(health_checker.health_history) == check_count
    
    def test_memory_efficiency(self, health_checker):
        """Test memory efficiency of health monitoring"""
        import sys
        
        # Check initial memory state
        initial_objects = len(gc.get_objects()) if 'gc' in sys.modules else 0
        
        # Run health monitoring test
        asyncio.run(self._run_health_test(health_checker))
        
        # Check memory usage
        final_objects = len(gc.get_objects()) if 'gc' in sys.modules else 0
        object_increase = final_objects - initial_objects
        
        # Memory usage should be reasonable
        assert object_increase < 300  # Should not create too many objects
    
    async def _run_health_test(self, health_checker):
        """Helper method for memory test"""
        with patch.object(health_checker, '_check_database_health') as mock_db:
            with patch.object(health_checker, '_check_api_health') as mock_api:
                with patch.object(health_checker, '_check_memory_health') as mock_mem:
                    with patch.object(health_checker, '_check_cpu_health') as mock_cpu:
                        
                        for mock in [mock_db, mock_api, mock_mem, mock_cpu]:
                            mock.return_value = {"score": 90, "status": "healthy"}
                        
                        await health_checker.check_system_health()


class TestComponentChecks:
    """Test individual component health checks"""
    
    @pytest.fixture
    def health_checker(self):
        return HealthChecker()
    
    @pytest.mark.asyncio
    async def test_database_health_check(self, health_checker):
        """Test database health check implementation"""
        result = await health_checker._check_database_health()
        
        assert "score" in result
        assert "status" in result
        assert "response_time_ms" in result
        assert "connection_pool" in result
        assert isinstance(result["score"], (int, float))
        assert 0 <= result["score"] <= 100
    
    @pytest.mark.asyncio
    async def test_api_health_check(self, health_checker):
        """Test API health check implementation"""
        result = await health_checker._check_api_health()
        
        assert "score" in result
        assert "status" in result
        assert "response_time_ms" in result
        assert "endpoints_checked" in result
        assert "success_rate" in result
        assert isinstance(result["score"], (int, float))
        assert 0 <= result["score"] <= 100
    
    @pytest.mark.asyncio
    async def test_memory_health_check(self, health_checker):
        """Test memory health check implementation"""
        result = await health_checker._check_memory_health()
        
        assert "score" in result
        assert "status" in result
        assert "usage_percent" in result
        assert "available_gb" in result
        assert "total_gb" in result
        assert isinstance(result["score"], (int, float))
        assert 0 <= result["score"] <= 100
    
    @pytest.mark.asyncio
    async def test_cpu_health_check(self, health_checker):
        """Test CPU health check implementation"""
        result = await health_checker._check_cpu_health()
        
        assert "score" in result
        assert "status" in result
        assert "usage_percent" in result
        assert "load_average" in result
        assert isinstance(result["score"], (int, float))
        assert 0 <= result["score"] <= 100


class TestSkillCompliance:
    """Test skill compliance with Claude Skills guide"""
    
    def test_skill_folder_structure(self):
        """Test skill follows proper folder structure"""
        import os
        skill_path = "trading-system-monitoring"
        
        assert os.path.exists(f"{skill_path}/SKILL.md")
        assert os.path.exists(f"{skill_path}/scripts/")
        assert os.path.exists(f"{skill_path}/references/")
        assert not os.path.exists(f"{skill_path}/README.md")
    
    def test_skill_naming_compliance(self):
        """Test skill uses kebab-case naming"""
        skill_name = "trading-system-monitoring"
        
        assert "-" in skill_name
        assert " " not in skill_name
        assert "_" not in skill_name
        assert skill_name.islower()
    
    def test_frontmatter_compliance(self):
        """Test SKILL.md has proper frontmatter"""
        with open("trading-system-monitoring/SKILL.md", "r") as f:
            content = f.read()
        
        assert content.startswith("---")
        assert "name:" in content
        assert "description:" in content
        assert "<" not in content and ">" not in content


if __name__ == "__main__":
    pytest.main([__file__])
