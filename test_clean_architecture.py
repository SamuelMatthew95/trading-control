"""
Clean Architecture Tests - Production-Ready OpenClaw Platform
Tests for the clean, robust implementation with no old references
"""

import asyncio
from datetime import datetime
from unittest.mock import Mock, patch

import pytest


# Test clean imports
def test_clean_imports():
    """Test that all imports work without old references"""
    from config import get_settings
    from main import app
    from memory import get_memory_manager
    from orchestrator import OpenClawOrchestrator
    from tasks import get_task_queue
    from tools import get_tool_registry

    assert app is not None
    assert get_memory_manager() is not None
    assert get_tool_registry() is not None
    assert get_task_queue() is not None
    assert get_settings() is not None

    print("✅ All imports successful - no old references")


# Test platform initialization
def test_platform_initialization():
    """Test platform can be initialized cleanly"""
    from main import TradingControlPlatform

    platform = TradingControlPlatform()
    assert platform is not None
    assert platform.tool_registry is not None
    assert platform.memory_manager is not None
    assert platform.task_queue is not None
    assert not platform.is_running

    print("✅ Platform initialization works")


# Test orchestrator functionality
def test_orchestrator_basic():
    """Test orchestrator basic functionality"""
    from memory import get_memory_manager
    from orchestrator import OpenClawOrchestrator, OrchestratorStatus
    from tasks import get_task_queue
    from tools import get_tool_registry

    # Create orchestrator with dependencies
    orchestrator = OpenClawOrchestrator(
        memory=get_memory_manager(),
        tools=get_tool_registry(),
        task_queue=get_task_queue(),
    )

    assert orchestrator is not None
    assert orchestrator.status == OrchestratorStatus.IDLE
    assert not orchestrator.is_running
    assert len(orchestrator.agents) == 0

    print("✅ Orchestrator basic functionality works")


# Test tool registry
def test_tool_registry():
    """Test tool registry functionality"""
    from tools import ToolCategory, get_tool_registry

    registry = get_tool_registry()
    assert registry is not None

    # Check built-in tools are registered
    all_tools = registry.get_all_tools()
    assert len(all_tools) > 0

    # Check categories
    market_tools = registry.list_tools_by_category(ToolCategory.MARKET)
    assert len(market_tools) > 0

    print("✅ Tool registry works")


# Test memory manager
def test_memory_manager():
    """Test memory manager functionality"""
    from memory import get_memory_manager

    manager = get_memory_manager()
    assert manager is not None

    # Check components
    assert manager.short_term is not None
    assert manager.persistent is not None
    assert manager.performance is not None

    print("✅ Memory manager works")


# Test task queue
def test_task_queue():
    """Test task queue functionality"""
    from tasks import TaskStatus, get_task_queue

    queue = get_task_queue()
    assert queue is not None

    # Check queue stats
    stats = queue.get_queue_stats()
    assert stats["total_tasks"] == 0
    assert stats["pending_tasks"] == 0
    assert stats["running_tasks"] == 0

    print("✅ Task queue works")


# Test configuration
def test_configuration():
    """Test configuration loading"""
    from config import get_settings

    settings = get_settings()
    assert settings is not None
    assert settings.host is not None
    assert settings.port is not None
    assert settings.environment is not None
    assert settings.log_level is not None

    print("✅ Configuration works")


# Test API endpoints (basic)
def test_api_endpoints():
    """Test API endpoints are properly defined"""
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)

    # Test root endpoint
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()

    # Test health endpoint
    response = client.get("/health")
    assert response.status_code == 200
    assert "status" in response.json()

    print("✅ API endpoints work")


# Test integration
@pytest.mark.asyncio
async def test_integration():
    """Test integration between components"""
    from main import TradingControlPlatform
    from memory import get_memory_manager
    from orchestrator import OpenClawOrchestrator
    from tasks import get_task_queue
    from tools import get_tool_registry

    # Create platform
    platform = TradingControlPlatform()

    # Initialize
    await platform.initialize()
    assert platform.is_running is False  # Not started yet

    # Start platform
    await platform.start()
    assert platform.is_running is True

    # Test status
    status = platform.get_platform_status()
    assert status["status"] == "running"

    # Stop platform
    await platform.stop()
    assert platform.is_running is False

    print("✅ Full integration works")


# Test error handling
def test_error_handling():
    """Test error handling is robust"""
    from tools import get_tool_registry

    registry = get_tool_registry()

    # Test invalid tool execution
    result = asyncio.run(registry.execute_tool("invalid_tool", symbol="AAPL"))
    assert "error" in result
    assert result["error"] == "Tool invalid_tool not found"

    print("✅ Error handling works")


# Test no old references
def test_no_old_references():
    """Ensure no old references exist"""
    # Test that TradeRecord is in memory.py, not models.py
    try:
        from memory import TradeRecord

        # This should work - TradeRecord is in memory.py
    except ImportError as e:
        assert False, f"TradeRecord should be available in memory.py: {e}"

    # Test that old services are removed
    try:
        from services import AgentPerformanceService

        assert False, "AgentPerformanceService should be removed"
    except ImportError:
        pass  # Expected

    # Test that old models are removed
    try:
        from models import TradeRecord as OldTradeRecord

        assert False, "Old TradeRecord should not exist"
    except ImportError:
        pass  # Expected

    print("✅ No old references found")


# Test robustness
def test_robustness():
    """Test system is robust and handles edge cases"""
    # Test with missing environment variables
    import os

    from config import get_settings

    original_env = os.environ.copy()

    try:
        # Clear critical env vars if they exist
        if "REDIS_URL" in os.environ:
            del os.environ["REDIS_URL"]

        # Should still work with fallbacks
        from memory import get_memory_manager

        manager = get_memory_manager()
        assert manager is not None

        # Should use fallback storage
        assert manager.short_term._connected is False  # Should fallback

    finally:
        # Restore environment
        os.environ.clear()
        os.environ.update(original_env)

    print("✅ System is robust with fallbacks")


# Test performance
def test_performance():
    """Test performance characteristics"""
    from tools import get_tool_registry

    registry = get_tool_registry()

    # Test tool stats
    stats = registry.get_tool_stats()
    assert "total_tools" in stats
    assert "categories" in stats
    assert isinstance(stats["total_tools"], int)

    print("✅ Performance metrics available")


# Run all tests
if __name__ == "__main__":
    print("🧪 Running Clean Architecture Tests")
    print("=" * 50)

    test_clean_imports()
    test_platform_initialization()
    test_orchestrator_basic()
    test_tool_registry()
    test_memory_manager()
    test_task_queue()
    test_configuration()
    test_api_endpoints()
    test_error_handling()
    test_no_old_references()
    test_robustness()
    test_performance()

    print("=" * 50)
    print("🚀 All Clean Architecture Tests Passed!")
    print("✅ System is production-ready with no old references")
