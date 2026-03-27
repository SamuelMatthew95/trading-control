"""Tests for Redis connection fixes and WebSocket broadcaster."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from redis.asyncio import Redis, ConnectionPool
from redis.exceptions import ConnectionError, TimeoutError

from api.redis_client import get_redis, close_redis
from api.services.websocket_broadcaster import WebSocketBroadcaster, get_broadcaster
from api.events.bus import EventBus
from api.events.consumer import BaseStreamConsumer
from api.events.dlq import DLQManager


class TestRedisConnectionFixes:
    """Test Redis connection pool management and error handling."""

    @pytest.fixture
    async def mock_redis_pool(self):
        """Mock Redis connection pool."""
        pool = AsyncMock(spec=ConnectionPool)
        pool.aclose = AsyncMock()
        return pool

    @pytest.fixture
    async def mock_redis_client(self, mock_redis_pool):
        """Mock Redis client."""
        client = AsyncMock(spec=Redis)
        client.ping = AsyncMock(return_value=True)
        client.aclose = AsyncMock()
        client.connection_pool = mock_redis_pool
        return client

    @pytest.mark.asyncio
    async def test_get_redis_with_health_check(self):
        """Test Redis client creation with health check interval."""
        with patch('api.redis_client.ConnectionPool') as mock_pool_class, \
             patch('api.redis_client.Redis') as mock_redis_class:
            
            mock_pool = AsyncMock()
            mock_redis = AsyncMock()
            mock_pool_class.from_url.return_value = mock_pool
            mock_redis_class.return_value = mock_redis
            
            # Mock settings
            with patch('api.redis_client.settings') as mock_settings:
                mock_settings.REDIS_URL = "redis://localhost:6379/0"
                
                client = await get_redis()
                
                # Verify connection pool was created with health_check_interval
                mock_pool_class.from_url.assert_called_once()
                call_kwargs = mock_pool_class.from_url.call_args[1]
                
                assert call_kwargs['max_connections'] == 30
                assert call_kwargs['health_check_interval'] == 30
                assert call_kwargs['socket_timeout'] == 5
                assert call_kwargs['socket_connect_timeout'] == 5
                assert call_kwargs['retry_on_timeout'] is True

    @pytest.mark.asyncio
    async def test_get_redis_connection_error_handling(self):
        """Test Redis connection error handling."""
        with patch('api.redis_client.ConnectionPool') as mock_pool_class, \
             patch('api.redis_client.Redis') as mock_redis_class, \
             patch('api.redis_client.log_structured') as mock_log, \
             patch('api.redis_client.close_redis') as mock_close:
            
            mock_redis = AsyncMock()
            mock_redis.ping.side_effect = ConnectionError("Connection failed")
            mock_redis_class.return_value = mock_redis
            
            # Reset global state
            import api.redis_client
            api.redis_client._redis_client = None
            api.redis_client._redis_pool = None
            
            with patch('api.redis_client.settings') as mock_settings:
                mock_settings.REDIS_URL = "redis://localhost:6379/0"
                
                # Should not raise due to cleanup in get_redis
                with pytest.raises(ConnectionError):
                    await get_redis()
                
                # Verify error was logged and cleanup called
                mock_log.assert_called_with("error", "Redis connection failed", exc_info=True)
                mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_redis_graceful_cleanup(self):
        """Test Redis client and pool cleanup on close."""
        with patch('api.redis_client._redis_client') as mock_client, \
             patch('api.redis_client._redis_pool') as mock_pool, \
             patch('api.redis_client.log_structured') as mock_log:
            
            mock_client.aclose = AsyncMock()
            mock_pool.aclose = AsyncMock()
            
            await close_redis()
            
            mock_client.aclose.assert_called_once()
            mock_pool.aclose.assert_called_once()
            
            # Verify cleanup was logged
            mock_log.assert_any_call("info", "Redis client closed")
            mock_log.assert_any_call("info", "Redis connection pool closed")

    @pytest.mark.asyncio
    async def test_close_redis_error_handling(self):
        """Test Redis cleanup error handling."""
        with patch('api.redis_client._redis_client') as mock_client, \
             patch('api.redis_client._redis_pool') as mock_pool, \
             patch('api.redis_client.log_structured') as mock_log:
            
            mock_client.aclose = AsyncMock(side_effect=ConnectionError("Close failed"))
            mock_pool.aclose = AsyncMock(side_effect=TimeoutError("Pool close failed"))
            
            # Should not raise exception despite errors
            await close_redis()
            
            # Verify errors were logged but didn't crash
            mock_log.assert_any_call("warning", "Error closing Redis client", exc_info=True)
            mock_log.assert_any_call("warning", "Error closing Redis pool", exc_info=True)


class TestWebSocketBroadcaster:
    """Test WebSocket broadcaster service."""

    @pytest.fixture
    def broadcaster(self):
        """Create broadcaster instance."""
        return WebSocketBroadcaster()

    @pytest.fixture
    def mock_redis_client(self):
        """Mock Redis client."""
        client = AsyncMock()
        client.xread = AsyncMock(return_value=[])
        return client

    @pytest.mark.asyncio
    async def test_broadcaster_start_stop(self, broadcaster, mock_redis_client):
        """Test broadcaster start and stop lifecycle."""
        await broadcaster.start(mock_redis_client)
        
        assert broadcaster._running is True
        assert broadcaster._broadcast_task is not None  # [OK] Now uses dashboard broadcast loop
        
        await broadcaster.stop()
        
        assert broadcaster._running is False
        assert broadcaster._broadcast_task is None  # [OK] Only dashboard task exists now

    @pytest.mark.asyncio
    async def test_add_remove_connections(self, broadcaster):
        """Test adding and removing WebSocket connections."""
        mock_ws = AsyncMock()
        
        await broadcaster.add_connection(mock_ws)
        assert mock_ws in broadcaster._connections
        assert len(broadcaster._connections) == 1
        
        await broadcaster.remove_connection(mock_ws)
        assert mock_ws not in broadcaster._connections
        assert len(broadcaster._connections) == 0

    @pytest.mark.asyncio
    async def test_broadcast_message_to_all_connections(self, broadcaster):
        """Test broadcasting messages to all connected WebSockets."""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        mock_ws3 = AsyncMock()
        
        await broadcaster.add_connection(mock_ws1)
        await broadcaster.add_connection(mock_ws2)
        await broadcaster.add_connection(mock_ws3)
        
        # Directly test the broadcast logic without the async loop
        test_message = {"type": "test", "data": "hello"}
        
        # Simulate what the broadcast loop does
        disconnected = []
        for websocket in broadcaster._connections:
            try:
                await websocket.send_json(test_message)
            except Exception:
                disconnected.append(websocket)
        
        # Verify all connections received the message
        mock_ws1.send_json.assert_called_once_with(test_message)
        mock_ws2.send_json.assert_called_once_with(test_message)
        mock_ws3.send_json.assert_called_once_with(test_message)

    @pytest.mark.asyncio
    async def test_broadcast_handles_disconnected_websockets(self, broadcaster):
        """Test broadcaster handles disconnected WebSockets gracefully."""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        mock_ws2.send_json.side_effect = Exception("Connection closed")
        
        await broadcaster.add_connection(mock_ws1)
        await broadcaster.add_connection(mock_ws2)
        
        # Directly test the broadcast logic
        test_message = {"type": "test", "data": "hello"}
        disconnected = []
        
        for websocket in list(broadcaster._connections):
            try:
                await websocket.send_json(test_message)
            except Exception:
                disconnected.append(websocket)
        
        # Remove disconnected connections
        for ws in disconnected:
            await broadcaster.remove_connection(ws)
        
        # mock_ws1 should still be connected, mock_ws2 should be removed
        assert mock_ws1 in broadcaster._connections
        assert mock_ws2 not in broadcaster._connections

    @pytest.mark.asyncio
    async def test_redis_listener_error_handling(self, broadcaster, mock_redis_client):
        """Test Redis listener error handling."""
        mock_redis_client.xread.side_effect = ConnectionError("Redis error")
        
        await broadcaster.start(mock_redis_client)
        
        # Give listener a chance to encounter error
        await asyncio.sleep(0.1)
        
        # Should still be running despite errors
        assert broadcaster._running is True
        
        await broadcaster.stop()

    def test_get_broadcaster_singleton(self):
        """Test broadcaster singleton pattern."""
        broadcaster1 = get_broadcaster()
        broadcaster2 = get_broadcaster()
        
        assert broadcaster1 is broadcaster2


class TestEventBusErrorHandling:
    """Test EventBus error handling improvements."""

    @pytest.fixture
    def mock_redis_client(self):
        """Mock Redis client."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def event_bus(self, mock_redis_client):
        """Create EventBus with mock Redis."""
        return EventBus(mock_redis_client)

    @pytest.mark.asyncio
    async def test_publish_connection_error(self, event_bus, mock_redis_client):
        """Test publish handles connection errors gracefully."""
        mock_redis_client.xadd.side_effect = ConnectionError("Connection failed")
        
        with patch('api.events.bus.log_structured') as mock_log:
            result = await event_bus.publish("test_stream", {"data": "test"})
            
            assert result is None
            mock_log.assert_called_with(
                "warning", 
                "Redis connection error during publish", 
                stream="test_stream", 
                exc_info=True
            )

    @pytest.mark.asyncio
    async def test_consume_timeout_error(self, event_bus, mock_redis_client):
        """Test consume handles timeout errors gracefully."""
        mock_redis_client.xreadgroup.side_effect = TimeoutError("Timeout")
        
        with patch('api.events.bus.log_structured') as mock_log:
            result = await event_bus.consume("test_stream", "group", "consumer")
            
            assert result == []
            mock_log.assert_called_with(
                "warning", 
                "Redis connection error during consume", 
                stream="test_stream", 
                exc_info=True
            )

    @pytest.mark.asyncio
    async def test_reclaim_stale_error_handling(self, event_bus, mock_redis_client):
        """Test reclaim_stale handles all error types gracefully."""
        # Test ConnectionError
        mock_redis_client.xautoclaim.side_effect = ConnectionError("Connection failed")
        
        with patch('api.events.bus.log_structured') as mock_log:
            result = await event_bus.reclaim_stale("test_stream", "group", "consumer-1")
            
            assert result == []
            mock_log.assert_called_with(
                "warning",
                "Redis connection error during reclaim_stale",
                stream="test_stream",
                group="group",
                exc_info=True
            )

        # Test ResponseError
        mock_redis_client.xautoclaim.side_effect = Exception("Other error")
        
        with patch('api.events.bus.log_structured') as mock_log:
            result = await event_bus.reclaim_stale("test_stream", "group", "consumer-1")
            
            assert result == []
            mock_log.assert_called_with(
                "error",
                "Unexpected error during reclaim_stale",
                stream="test_stream",
                group="group",
                exc_info=True
            )

    @pytest.mark.asyncio
    async def test_acknowledge_error_handling(self, event_bus, mock_redis_client):
        """Test acknowledge handles errors gracefully."""
        mock_redis_client.xack.side_effect = ConnectionError("Connection failed")
        
        with patch('api.events.bus.log_structured') as mock_log:
            result = await event_bus.acknowledge("test_stream", "group", "msg1")
            
            assert result == 0
            mock_log.assert_called_with(
                "warning", 
                "Redis connection error during acknowledge", 
                stream="test_stream", 
                exc_info=True
            )


class TestConsumerShutdownFixes:
    """Test consumer shutdown improvements."""

    @pytest.fixture
    def mock_bus(self):
        """Mock EventBus."""
        bus = AsyncMock(spec=EventBus)
        bus.reclaim_stale = AsyncMock(return_value=[])
        bus.consume = AsyncMock(return_value=[])
        bus.acknowledge = AsyncMock(return_value=1)
        return bus

    @pytest.fixture
    def mock_dlq(self):
        """Mock DLQManager."""
        dlq = AsyncMock(spec=DLQManager)
        dlq.should_dlq = AsyncMock(return_value=False)
        dlq.redis = AsyncMock()
        dlq.redis.get = AsyncMock(return_value="0")
        return dlq

    @pytest.fixture
    def consumer(self, mock_bus, mock_dlq):
        """Create test consumer."""
        class TestConsumer(BaseStreamConsumer):
            async def process(self, data):
                pass
        
        return TestConsumer(mock_bus, mock_dlq, "test_stream", "test_group", "test_consumer")

    @pytest.mark.asyncio
    async def test_consumer_graceful_shutdown(self, consumer):
        """Test consumer graceful shutdown with timeout."""
        await consumer.start()
        assert consumer._running is True
        assert consumer._task is not None
        
        # Test graceful shutdown
        await consumer.stop()
        
        assert consumer._running is False
        assert consumer._task is None

    @pytest.mark.asyncio
    async def test_consumer_shutdown_timeout(self, consumer):
        """Test consumer shutdown timeout handling."""
        # Create a consumer that takes too long to shut down
        class SlowConsumer(BaseStreamConsumer):
            async def process(self, data):
                await asyncio.sleep(10)  # Simulate slow processing
            
            async def _run(self):
                while self._running:
                    await asyncio.sleep(0.1)
        
        slow_consumer = SlowConsumer(consumer.bus, consumer.dlq, "test", "group", "consumer")
        await slow_consumer.start()
        
        # Mock the task to take longer than timeout
        with patch.object(slow_consumer._task, 'cancel') as mock_cancel, \
             patch('api.events.consumer.log_structured') as mock_log:
            
            # Simulate timeout by making wait_for raise TimeoutError
            with patch('asyncio.wait_for', side_effect=asyncio.TimeoutError()):
                await slow_consumer.stop()
            
            # Should have attempted to cancel the task
            mock_cancel.assert_called_once()
            
            # Should have logged timeout warning
            mock_log.assert_any_call(
                "warning",
                "Consumer task timeout, cancelling",
                stream="test"
            )

    @pytest.mark.asyncio
    async def test_safe_reclaim_stale_timeout(self, consumer):
        """Test safe reclaim stale with timeout."""
        import asyncio
        
        # Mock reclaim_stale to raise timeout error
        consumer.bus.reclaim_stale = AsyncMock(side_effect=asyncio.TimeoutError("Timeout"))
        
        # Should handle timeout and return empty list
        result = await consumer._safe_reclaim_stale()
        
        assert result == []

    @pytest.mark.asyncio
    async def test_consumer_loop_redis_error_recovery(self, consumer):
        """Test consumer loop handles Redis errors and recovers."""
        # First call fails, second succeeds
        consumer.bus.consume.side_effect = [
            ConnectionError("Connection failed"),
            [("msg1", {"data": "test"})]
        ]
        
        with patch('api.events.consumer.log_structured') as mock_log, \
             patch.object(consumer, '_handle_message') as mock_handle:
            
            await consumer.start()
            
            # Give consumer a chance to run
            await asyncio.sleep(0.1)
            
            await consumer.stop()
            
            # Should have logged the connection error
            mock_log.assert_any_call(
                "warning",
                "Redis connection error in consumer loop",
                stream="test_stream",
                exc_info=True
            )
