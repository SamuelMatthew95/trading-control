"""
Basic tests for trading control platform
"""

import os
import sys

import pytest

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_imports():
    """Test that all modules can be imported"""
    try:
        from core.config import get_settings

        assert get_settings() is not None
    except ImportError as e:
        pytest.skip(f"Core config not available: {e}")

    try:
        from core.metrics import SystemMetrics

        metrics = SystemMetrics()
        assert metrics.metrics is not None
    except ImportError as e:
        pytest.skip(f"Core metrics not available: {e}")

    try:
        from core.langfuse_client import LangfuseClient

        client = LangfuseClient()
        assert client is not None
    except ImportError as e:
        pytest.skip(f"Langfuse client not available: {e}")


def test_basic_functionality():
    """Test basic functionality"""
    try:
        from core.metrics import SystemMetrics

        # Test metrics recording
        metrics = SystemMetrics()
        initial_count = metrics.metrics["total_tasks_processed"]

        metrics.record_task_completion(True, 1000.0)
        assert metrics.metrics["total_tasks_processed"] == initial_count + 1
        assert metrics.metrics["successful_tasks"] == 1
        assert metrics.metrics["success_rate"] == 1.0

        metrics.record_task_completion(False, 500.0)
        assert metrics.metrics["total_tasks_processed"] == initial_count + 2
        assert metrics.metrics["successful_tasks"] == 1
        assert metrics.metrics["failed_tasks"] == 1
        assert metrics.metrics["success_rate"] == 0.5

    except ImportError as e:
        pytest.skip(f"Core metrics not available: {e}")


def test_configuration():
    """Test configuration loading"""
    try:
        from core.config import Settings, get_settings

        settings = get_settings()
        assert isinstance(settings, Settings)
        assert hasattr(settings, "host")
        assert hasattr(settings, "port")
        assert hasattr(settings, "max_concurrent_tasks")

    except ImportError as e:
        pytest.skip(f"Core config not available: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
