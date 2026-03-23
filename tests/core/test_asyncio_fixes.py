"""Test asyncio.wait_for bug fixes and graceful shutdown behavior."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from api.main import _retry_loop, monitor_consumer_lag, monitor_llm_cost


class TestAsyncioFixes:
    """Test that the asyncio.wait_for bugs are fixed and shutdown works gracefully."""

    @pytest.mark.asyncio
    async def test_retry_loop_shutdown_immediately(self):
        """Test _retry_loop exits immediately when stop_event is set."""
        stop_event = asyncio.Event()
        stop_event.set()  # Set immediately

        # Mock the service to avoid actual DB calls
        mock_service = AsyncMock()

        with pytest.MonkeyPatch().context() as m:
            m.setattr("api.main_state.get_run_lifecycle_service", lambda: mock_service)

            # Should exit quickly without sleeping
            start_time = asyncio.get_event_loop().time()
            await _retry_loop(stop_event)
            elapsed = asyncio.get_event_loop().time() - start_time

            # Should complete quickly (under 1 second)
            assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_retry_loop_shutdown_after_delay(self):
        """Test _retry_loop exits after stop_event is set during execution."""
        stop_event = asyncio.Event()
        mock_service = AsyncMock()

        async def set_stop_after_delay():
            await asyncio.sleep(0.1)  # Small delay
            stop_event.set()

        with pytest.MonkeyPatch().context() as m:
            m.setattr("api.main_state.get_run_lifecycle_service", lambda: mock_service)

            # Run both the retry loop and the stop setter
            task = asyncio.create_task(_retry_loop(stop_event))
            await asyncio.create_task(set_stop_after_delay())

            start_time = asyncio.get_event_loop().time()
            await task
            elapsed = asyncio.get_event_loop().time() - start_time

            # Should complete within reasonable time (sleep was interrupted)
            assert elapsed < 2.0  # Much less than 3600 second sleep

    @pytest.mark.asyncio
    async def test_monitor_consumer_lag_shutdown_immediately(self):
        """Test monitor_consumer_lag exits immediately when stop_event is set."""
        stop_event = asyncio.Event()
        stop_event.set()  # Set immediately

        mock_bus = AsyncMock()
        mock_bus.get_stream_info.return_value = {}

        start_time = asyncio.get_event_loop().time()
        await monitor_consumer_lag(mock_bus, stop_event)
        elapsed = asyncio.get_event_loop().time() - start_time

        # Should complete quickly (under 1 second)
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_monitor_consumer_lag_shutdown_after_delay(self):
        """Test monitor_consumer_lag exits after stop_event is set during execution."""
        stop_event = asyncio.Event()
        mock_bus = AsyncMock()
        mock_bus.get_stream_info.return_value = {}

        async def set_stop_after_delay():
            await asyncio.sleep(0.1)  # Small delay
            stop_event.set()

        # Run both the monitor and the stop setter
        task = asyncio.create_task(monitor_consumer_lag(mock_bus, stop_event))
        await asyncio.create_task(set_stop_after_delay())

        start_time = asyncio.get_event_loop().time()
        await task
        elapsed = asyncio.get_event_loop().time() - start_time

        # Should complete within reasonable time (sleep was interrupted)
        assert elapsed < 2.0  # Much less than 30 second sleep

    @pytest.mark.asyncio
    async def test_monitor_llm_cost_shutdown_immediately(self):
        """Test monitor_llm_cost exits immediately when stop_event is set."""
        stop_event = asyncio.Event()
        stop_event.set()  # Set immediately

        mock_bus = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "0.0"

        start_time = asyncio.get_event_loop().time()
        await monitor_llm_cost(mock_bus, mock_redis, stop_event)
        elapsed = asyncio.get_event_loop().time() - start_time

        # Should complete quickly (under 1 second)
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_monitor_llm_cost_shutdown_after_delay(self):
        """Test monitor_llm_cost exits after stop_event is set during execution."""
        stop_event = asyncio.Event()
        mock_bus = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "0.0"

        async def set_stop_after_delay():
            await asyncio.sleep(0.1)  # Small delay
            stop_event.set()

        # Run both the monitor and the stop setter
        task = asyncio.create_task(monitor_llm_cost(mock_bus, mock_redis, stop_event))
        await asyncio.create_task(set_stop_after_delay())

        start_time = asyncio.get_event_loop().time()
        await task
        elapsed = asyncio.get_event_loop().time() - start_time

        # Should complete within reasonable time (sleep was interrupted)
        assert elapsed < 2.0  # Much less than 60 second sleep

    @pytest.mark.asyncio
    async def test_functions_dont_use_wait_for_anymore(self):
        """Test that the functions no longer use asyncio.wait_for pattern."""
        import inspect

        # Get source code of the functions
        retry_loop_source = inspect.getsource(_retry_loop)
        consumer_lag_source = inspect.getsource(monitor_consumer_lag)
        llm_cost_source = inspect.getsource(monitor_llm_cost)

        # Verify asyncio.wait_for is not used
        assert "asyncio.wait_for" not in retry_loop_source
        assert "asyncio.wait_for" not in consumer_lag_source
        assert "asyncio.wait_for" not in llm_cost_source

        # Verify the new pattern is used
        assert "asyncio.wait" in retry_loop_source
        assert "asyncio.wait" in consumer_lag_source
        assert "asyncio.wait" in llm_cost_source

        # Verify FIRST_COMPLETED is used
        assert "FIRST_COMPLETED" in retry_loop_source
        assert "FIRST_COMPLETED" in consumer_lag_source
        assert "FIRST_COMPLETED" in llm_cost_source
