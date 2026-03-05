"""
Test Configuration for Trading Control Platform
Comprehensive testing setup with pytest, coverage, and fixtures
"""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Generator
from unittest.mock import AsyncMock, Mock

import pytest

# Test configuration
pytest_plugins = []


# Test database setup
@pytest.fixture(scope="session")
def test_db_path() -> Generator[str, None, None]:
    """Create temporary test database"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    os.unlink(db_path)


@pytest.fixture(scope="session")
def test_config() -> Dict[str, Any]:
    """Test configuration"""
    return {
        "host": "localhost",
        "port": 8000,
        "debug": True,
        "environment": "test",
        "database": {"path": ":memory:", "connection_timeout": 5, "max_connections": 5},
        "langfuse": {
            "public_key": "test_key",
            "secret_key": "test_secret",
            "host": "https://test.langfuse.com",
        },
        "system": {
            "max_concurrent_tasks": 5,
            "task_queue_size": 100,
            "agent_pool_size": 3,
            "auto_scaling_enabled": True,
            "min_accuracy_threshold": 0.6,
            "max_error_rate_threshold": 0.1,
        },
    }


@pytest.fixture
def mock_observability():
    """Mock observability manager"""
    mock = Mock()
    mock.track_agent_execution = AsyncMock()
    mock.register_agent_with_mission_control = AsyncMock(return_value="test_agent_id")
    mock.flush_events = AsyncMock()
    mock.get_active_traces_count = Mock(return_value=0)
    return mock


@pytest.fixture
def mock_gateway():
    """Mock OpenClaw gateway"""
    mock = Mock()
    mock.start = AsyncMock()
    mock.stop = AsyncMock()
    mock.register_agent = AsyncMock(return_value="test_agent_id")
    mock.execute_task = AsyncMock()
    mock.get_agent_status = AsyncMock()
    mock.get_all_agents = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def sample_agent_data():
    """Sample agent data for testing"""
    return {
        "agent_id": "test_agent_001",
        "agent_type": "technical_analyst",
        "name": "Test Technical Analyst",
        "description": "Test agent for technical analysis",
        "version": "1.0.0",
        "capabilities": ["rsi", "macd", "bollinger"],
        "supported_task_types": ["analyze_symbol", "generate_signal"],
        "max_concurrent_tasks": 3,
        "timeout_seconds": 60,
    }


@pytest.fixture
def sample_task_data():
    """Sample task data for testing"""
    return {
        "task_id": "test_task_001",
        "task_type": "analyze_symbol",
        "input_data": {
            "symbol": "AAPL",
            "price_data": {
                "prices": [150.0, 152.0, 151.0, 153.0, 155.0],
                "volumes": [1000000, 1200000, 900000, 1500000, 1100000],
            },
            "indicators": ["rsi", "macd"],
        },
        "priority": 2,
        "timeout_seconds": 60,
    }


@pytest.fixture
def sample_financial_data():
    """Sample financial data for testing"""
    return {
        "symbol": "AAPL",
        "revenue": 365817000000,
        "net_income": 94680000000,
        "total_debt": 119000000000,
        "total_equity": 201000000000,
        "shares_outstanding": 15500000000,
        "current_price": 150.25,
        "previous_revenue": 365817000000,
        "previous_net_income": 94680000000,
    }


@pytest.fixture
def sample_news_data():
    """Sample news data for testing"""
    return {
        "articles": [
            {
                "title": "Apple beats earnings expectations",
                "content": "Apple reported strong quarterly earnings beating analyst expectations",
                "source": "Reuters",
                "timestamp": "2024-01-15T10:00:00Z",
            },
            {
                "title": "Apple announces new iPhone features",
                "content": "Apple announced new AI-powered features for upcoming iPhone models",
                "source": "TechCrunch",
                "timestamp": "2024-01-15T14:30:00Z",
            },
        ]
    }


@pytest.fixture
def sample_social_data():
    """Sample social media data for testing"""
    return {
        "posts": [
            {
                "content": "Bullish on AAPL! Great technical indicators",
                "author": "trader123",
                "likes": 150,
                "shares": 25,
                "comments": 12,
                "timestamp": "2024-01-15T09:15:00Z",
            },
            {
                "content": "AAPL looking strong, MACD showing bullish momentum",
                "author": "investor456",
                "likes": 89,
                "shares": 15,
                "comments": 8,
                "timestamp": "2024-01-15T11:30:00Z",
            },
        ]
    }


@pytest.fixture
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Test markers
pytest.mark.unit = pytest.mark.unit
pytest.mark.integration = pytest.mark.integration
pytest.mark.performance = pytest.mark.performance
pytest.mark.edge_case = pytest.mark.edge_case


# Coverage configuration
def pytest_configure(config):
    """Configure pytest for coverage"""
    config.addinivalue_line("markers", "unit: Unit tests (fast, isolated)")
    config.addinivalue_line(
        "markers", "integration: Integration tests (with external dependencies)"
    )
    config.addinivalue_line("markers", "performance: Performance tests (benchmarking)")
    config.addinivalue_line(
        "markers", "edge_case: Edge case tests (boundary conditions)"
    )


# Custom assertions
def assert_valid_agent_info(agent_info: Dict[str, Any]):
    """Assert agent info is valid"""
    required_fields = ["agent_id", "agent_type", "name", "version", "capabilities"]
    for field in required_fields:
        assert field in agent_info, f"Missing required field: {field}"
        assert agent_info[field], f"Empty required field: {field}"


def assert_valid_task_result(result: Dict[str, Any]):
    """Assert task result is valid"""
    required_fields = ["task_id", "status", "execution_time_ms"]
    for field in required_fields:
        assert field in result, f"Missing required field: {field}"

    assert result["status"] in ["completed", "failed", "cancelled"]
    assert result["execution_time_ms"] >= 0


def assert_valid_sentiment_analysis(analysis: Dict[str, Any]):
    """Assert sentiment analysis is valid"""
    required_fields = ["symbol", "overall_sentiment", "confidence"]
    for field in required_fields:
        assert field in analysis, f"Missing required field: {field}"

    assert analysis["overall_sentiment"] in ["positive", "negative", "neutral"]
    assert 0.0 <= analysis["confidence"] <= 1.0


def assert_valid_technical_analysis(analysis: Dict[str, Any]):
    """Assert technical analysis is valid"""
    required_fields = ["symbol", "indicators", "recommendations"]
    for field in required_fields:
        assert field in analysis, f"Missing required field: {field}"

    assert isinstance(analysis["indicators"], dict)
    assert isinstance(analysis["recommendations"], list)


def assert_valid_fundamental_analysis(analysis: Dict[str, Any]):
    """Assert fundamental analysis is valid"""
    required_fields = ["symbol", "metrics", "summary", "recommendations"]
    for field in required_fields:
        assert field in analysis, f"Missing required field: {field}"

    assert isinstance(analysis["metrics"], dict)
    assert isinstance(analysis["recommendations"], list)


# Test utilities
def create_mock_agent(
    agent_id: str = "test_agent", agent_type: str = "technical_analyst"
):
    """Create mock agent for testing"""
    agent = Mock()
    agent.agent_id = agent_id
    agent.get_agent_info.return_value = {
        "agent_id": agent_id,
        "agent_type": agent_type,
        "name": f"Test {agent_type}",
        "version": "1.0.0",
        "capabilities": ["test_capability"],
        "supported_task_types": ["test_task"],
        "max_concurrent_tasks": 3,
        "timeout_seconds": 60,
    }
    agent.get_supported_task_types.return_value = ["test_task"]
    agent.can_handle_task.return_value = True
    agent.validate_task.return_value = True
    return agent


def create_mock_task(task_id: str = "test_task", task_type: str = "test_task"):
    """Create mock task for testing"""
    from agent.interface import AgentTask

    return AgentTask(
        task_id=task_id,
        task_type=task_type,
        input_data={"test": "data"},
        metadata={},
        priority=1,
        timeout_seconds=60,
    )


def create_mock_result(task_id: str = "test_task", status: str = "completed"):
    """Create mock result for testing"""
    from agent.interface import AgentResult, AgentTaskStatus

    return AgentResult(
        task_id=task_id,
        status=AgentTaskStatus(status),
        output_data={"result": "test"},
        error_message=None,
        metrics={"test_metric": 1.0},
        trace_id="test_trace",
        tokens_used=100,
        cost_usd=0.002,
        execution_time_ms=100.0,
        started_at=datetime.now(),
        completed_at=datetime.now(),
    )


# Test data generators
def generate_price_data(count: int = 100, start_price: float = 100.0) -> list:
    """Generate realistic price data"""
    import random

    prices = [start_price]
    for _ in range(count - 1):
        change = random.uniform(-0.02, 0.02)  # 2% max change
        new_price = prices[-1] * (1 + change)
        prices.append(max(1.0, new_price))
    return prices


def generate_volume_data(count: int = 100, base_volume: int = 1000000) -> list:
    """Generate realistic volume data"""
    import random

    volumes = []
    for _ in range(count):
        volume = base_volume * random.uniform(0.5, 2.0)
        volumes.append(int(volume))
    return volumes


# Test environment setup
def setup_test_environment():
    """Setup test environment"""
    # Set test environment variables
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DEBUG"] = "false"
    os.environ["LOG_LEVEL"] = "DEBUG"

    # Create test directories
    test_dirs = ["logs", "data", "temp"]
    for dir_name in test_dirs:
        Path(dir_name).mkdir(exist_ok=True)


def cleanup_test_environment():
    """Cleanup test environment"""
    # Remove test directories
    test_dirs = ["logs", "data", "temp"]
    for dir_name in test_dirs:
        if Path(dir_name).exists():
            import shutil

            shutil.rmtree(dir_name)


# Pytest hooks
def pytest_sessionstart(session):
    """Setup test session"""
    setup_test_environment()


def pytest_sessionfinish(session):
    """Cleanup test session"""
    cleanup_test_environment()


# Async test utilities
async def run_async_test(coro, timeout: float = 5.0):
    """Run async test with timeout"""
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        pytest.fail(f"Test timed out after {timeout} seconds")


# Performance test utilities
def measure_execution_time(func, *args, **kwargs):
    """Measure execution time of a function"""
    import time

    start_time = time.time()
    result = func(*args, **kwargs)
    end_time = time.time()
    execution_time = end_time - start_time
    return result, execution_time


# Memory test utilities
def get_memory_usage():
    """Get current memory usage"""
    try:
        import psutil

        process = psutil.Process()
        return process.memory_info().rss
    except ImportError:
        return 0


# Database test utilities
def create_test_database(db_path: str):
    """Create test database with schema"""
    from models import create_database_tables

    create_database_tables(db_path)


def cleanup_test_database(db_path: str):
    """Clean up test database"""
    if os.path.exists(db_path):
        os.unlink(db_path)
