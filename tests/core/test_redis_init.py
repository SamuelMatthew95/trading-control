"""Tests for Redis stream initialization using fakeredis."""

from __future__ import annotations

import pytest
from redis.exceptions import ResponseError

from api.constants import (
    STREAM_AGENT_LOGS,
    STREAM_EXECUTIONS,
    STREAM_LEARNING_EVENTS,
    STREAM_MARKET_TICKS,
    STREAM_ORDERS,
    STREAM_RISK_ALERTS,
    STREAM_SIGNALS,
    STREAM_SYSTEM_METRICS,
)
from api.events.bus import DEFAULT_GROUP, STREAMS, EventBus


@pytest.mark.asyncio
async def test_happy_path_stream_creation(fake_redis):
    """Test 1: Happy path - all streams and groups created successfully."""
    # Ensure Redis is empty before test
    assert await fake_redis.dbsize() == 0

    # Run initialization
    event_bus = EventBus(fake_redis)
    await event_bus.create_groups()

    # Verify all streams were created by checking groups exist
    expected_streams = {
        STREAM_MARKET_TICKS,
        STREAM_SIGNALS,
        STREAM_ORDERS,
        STREAM_EXECUTIONS,
        STREAM_RISK_ALERTS,
        STREAM_LEARNING_EVENTS,
        STREAM_SYSTEM_METRICS,
        STREAM_AGENT_LOGS,  # Use constant instead of hardcoded string
    }

    # Check that groups exist for all streams
    for stream in expected_streams:
        # Try to get group info - this will fail if group doesn't exist
        groups = await fake_redis.xinfo_groups(stream)  # async call
        assert len(groups) == 1
        group_name = groups[0]["name"]
        if isinstance(group_name, bytes):
            group_name = group_name.decode()
        assert group_name == DEFAULT_GROUP


@pytest.mark.asyncio
async def test_idempotency_multiple_calls(fake_redis):
    """Test 2: Idempotency - calling twice doesn't crash."""
    # First call - should succeed
    event_bus = EventBus(fake_redis)
    await event_bus.create_groups()

    # Second call - should also succeed (BUSYGROUP handled silently)
    # This should not raise any exceptions
    await event_bus.create_groups()

    # Verify groups still exist (no duplicates)
    for stream in STREAMS:
        groups = await fake_redis.xinfo_groups(stream)  # async call
        assert len(groups) == 1  # Only one group per stream


@pytest.mark.asyncio
async def test_all_streams_have_consumers(fake_redis):
    """Test that all 7 streams can be consumed after initialization."""
    event_bus = EventBus(fake_redis)
    await event_bus.create_groups()

    # Test consuming from each stream
    for stream in STREAMS:
        try:
            messages = await event_bus.consume(
                stream, DEFAULT_GROUP, f"test_consumer_{stream}"
            )
            assert isinstance(messages, list)  # Should return a list (empty is fine)
        except Exception as exc:
            pytest.fail(f"Failed to consume from {stream}: {exc}")


@pytest.mark.asyncio
async def test_error_handling_unexpected_redis_error(fake_redis):
    """Test that unexpected Redis errors are properly raised."""
    # Mock xgroup_create to raise a non-BUSYGROUP error
    original_xgroup_create = fake_redis.xgroup_create

    async def failing_xgroup_create(*args, **kwargs):
        raise ResponseError("CONNECTION_LOST Redis connection lost")

    # Apply the mock
    fake_redis.xgroup_create = failing_xgroup_create

    # Should raise the unexpected error
    with pytest.raises(ResponseError) as exc_info:
        event_bus = EventBus(fake_redis)
        await event_bus.create_groups()

    assert "CONNECTION_LOST" in str(exc_info.value)

    # Restore original method
    fake_redis.xgroup_create = original_xgroup_create


@pytest.mark.asyncio
async def test_stream_creation_with_messages(fake_redis):
    """Test that streams work correctly with actual messages."""
    # Initialize streams
    event_bus = EventBus(fake_redis)
    await event_bus.create_groups()

    # Add a test message to a stream using EventBus.publish
    message_id = await event_bus.publish(
        "market_ticks",
        {"symbol": "BTC/USD", "price": "67000", "timestamp": "1234567890"},
    )
    assert message_id is not None

    # Verify stream has content
    length = await fake_redis.xlen("market_ticks")  # async call
    assert length == 1

    # Try to consume the message
    messages = await event_bus.consume("market_ticks", DEFAULT_GROUP, "test_consumer")

    # Should get the message we just added
    assert len(messages) == 1
    msg_id, payload = messages[0]
    assert payload["symbol"] == "BTC/USD"
    assert payload["price"] == "67000"


@pytest.mark.asyncio
async def test_group_id_parameter(fake_redis):
    """Test that the group is created with the correct id parameter ($ for new messages only)."""
    event_bus = EventBus(fake_redis)
    await event_bus.create_groups()

    # Add a message using EventBus.publish
    message_id = await event_bus.publish(
        "signals", {"signal": "BUY", "symbol": "ETH/USD"}
    )
    assert message_id is not None

    # Try to consume - should get the message since group was created before
    messages = await event_bus.consume("signals", DEFAULT_GROUP, "test_consumer")

    # Should get the message because it was added after group creation
    assert len(messages) == 1
    msg_id, payload = messages[0]
    assert payload["signal"] == "BUY"


if __name__ == "__main__":
    # Allow running tests directly
    import asyncio

    async def run_tests():
        print("TEST Running Redis init tests with fakeredis...")

        try:
            # Import fakeredis for direct testing
            import fakeredis

            # Test 1: Happy path
            print("\n1. Testing happy path...")
            fake_redis_1 = fakeredis.FakeAsyncRedis(decode_responses=True)
            await test_happy_path_stream_creation(fake_redis_1)
            await fake_redis_1.aclose()
            print("[OK] Happy path test passed")

            # Test 2: Idempotency
            print("\n2. Testing idempotency...")
            fake_redis_2 = fakeredis.FakeAsyncRedis(decode_responses=True)
            await test_idempotency_multiple_calls(fake_redis_2)
            await fake_redis_2.aclose()
            print("[OK] Idempotency test passed")

            # Test 3: Skip startup order (removed - was flaky)
            print("\n3. Skipping startup order test (removed - was flaky)")
            print("[OK] Startup order test skipped")

            # Test 4: All streams consumable
            print("\n4. Testing all streams consumable...")
            fake_redis_4 = fakeredis.FakeAsyncRedis(decode_responses=True)
            await test_all_streams_have_consumers(fake_redis_4)
            await fake_redis_4.aclose()
            print("[OK] All streams consumable test passed")

            # Test 5: Message handling
            print("\n5. Testing message handling...")
            fake_redis_5 = fakeredis.FakeAsyncRedis(decode_responses=True)
            await test_stream_creation_with_messages(fake_redis_5)
            await fake_redis_5.aclose()
            print("[OK] Message handling test passed")

            # Test 6: Group id parameter
            print("\n6. Testing group id parameter...")
            fake_redis_6 = fakeredis.FakeAsyncRedis(decode_responses=True)
            await test_group_id_parameter(fake_redis_6)
            await fake_redis_6.aclose()
            print("[OK] Group id parameter test passed")

            print("\n All tests passed!")

        except Exception as exc:
            print(f"\n[FAIL] Test failed: {exc}")
            raise

    asyncio.run(run_tests())
