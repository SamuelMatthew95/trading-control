"""Tests for Redis stream initialization using fakeredis."""

from __future__ import annotations

import pytest
from redis.exceptions import ResponseError

from api.constants import (
    STREAM_EXECUTIONS,
    STREAM_LEARNING_EVENTS,
    STREAM_MARKET_TICKS,
    STREAM_ORDERS,
    STREAM_RISK_ALERTS,
    STREAM_SIGNALS,
    STREAM_SYSTEM_METRICS,
)
from api.events.bus import DEFAULT_GROUP, EventBus
from redis_init import ALL_STREAMS, ensure_redis_streams


@pytest.mark.asyncio
async def test_happy_path_stream_creation(fake_redis):
    """Test 1: Happy path - all streams and groups created successfully."""
    # Ensure Redis is empty before test
    assert await fake_redis.dbsize() == 0

    # Run initialization
    await ensure_redis_streams(fake_redis)

    # Verify all streams were created by checking groups exist
    expected_streams = {
        STREAM_MARKET_TICKS,
        STREAM_SIGNALS,
        STREAM_ORDERS,
        STREAM_EXECUTIONS,
        STREAM_RISK_ALERTS,
        STREAM_LEARNING_EVENTS,
        STREAM_SYSTEM_METRICS,
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
    await ensure_redis_streams(fake_redis)

    # Second call - should also succeed (BUSYGROUP handled silently)
    # This should not raise any exceptions
    await ensure_redis_streams(fake_redis)

    # Verify groups still exist (no duplicates)
    for stream in ALL_STREAMS:
        groups = await fake_redis.xinfo_groups(stream)  # async call
        assert len(groups) == 1  # Only one group per stream


@pytest.mark.asyncio
async def test_startup_order_fix(fake_redis):
    """Test 3: Startup order - proves the fix solves the original bug."""
    # Step 1: Worker tries to read before init - should fail
    event_bus = EventBus(fake_redis)

    with pytest.raises(ResponseError) as exc_info:
        await event_bus.consume("market_ticks", DEFAULT_GROUP, "test_consumer")

    # fakeredis gives a different error message, but it's still a NOGROUP-like error
    error_msg = str(exc_info.value)
    assert "key to exist" in error_msg or "NOGROUP" in error_msg

    # Step 2: Run initialization
    await ensure_redis_streams(fake_redis)

    # Step 3: Worker tries to read after init - should succeed
    try:
        # This should not raise an exception
        messages = await event_bus.consume(
            "market_ticks", DEFAULT_GROUP, "test_consumer"
        )
        assert isinstance(messages, list)  # Should return a list (empty is fine)
    except ResponseError as exc:
        pytest.fail(f"XREADGROUP failed after init: {exc}")


@pytest.mark.asyncio
async def test_all_streams_have_consumers(fake_redis):
    """Test that all 7 streams can be consumed after initialization."""
    await ensure_redis_streams(fake_redis)
    event_bus = EventBus(fake_redis)

    # Test consuming from each stream
    for stream in ALL_STREAMS:
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
        await ensure_redis_streams(fake_redis)

    assert "CONNECTION_LOST" in str(exc_info.value)

    # Restore original method
    fake_redis.xgroup_create = original_xgroup_create


@pytest.mark.asyncio
async def test_manual_redis_client_creation():
    """Test the function can create its own Redis client when none provided."""
    # This test verifies the function signature works
    # We can't test actual Redis connection without a real instance
    try:
        # Should not crash when called without parameters
        # It will fail to connect to Redis, but that's expected in test
        with pytest.raises(Exception):  # Should fail to connect to Redis
            await ensure_redis_streams()
    except ImportError:
        # If redis module is not available, that's also fine for this test
        pass


@pytest.mark.asyncio
async def test_stream_creation_with_messages(fake_redis):
    """Test that streams work correctly with actual messages."""
    # Initialize streams
    await ensure_redis_streams(fake_redis)

    # Add a test message to a stream using EventBus.publish
    event_bus = EventBus(fake_redis)
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
    await ensure_redis_streams(fake_redis)

    # Add a message using EventBus.publish
    event_bus = EventBus(fake_redis)
    message_id = await event_bus.publish("signals", {"signal": "BUY", "symbol": "ETH/USD"})
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
        print("🧪 Running Redis init tests with fakeredis...")

        try:
            # Import fakeredis for direct testing
            import fakeredis

            # Test 1: Happy path
            print("\n1️⃣ Testing happy path...")
            fake_redis_1 = fakeredis.FakeAsyncRedis(decode_responses=True)
            await test_happy_path_stream_creation(fake_redis_1)
            await fake_redis_1.aclose()
            print("✅ Happy path test passed")

            # Test 2: Idempotency
            print("\n2️⃣ Testing idempotency...")
            fake_redis_2 = fakeredis.FakeAsyncRedis(decode_responses=True)
            await test_idempotency_multiple_calls(fake_redis_2)
            await fake_redis_2.aclose()
            print("✅ Idempotency test passed")

            # Test 3: Startup order
            print("\n3️⃣ Testing startup order fix...")
            fake_redis_3 = fakeredis.FakeAsyncRedis(decode_responses=True)
            await test_startup_order_fix(fake_redis_3)
            await fake_redis_3.aclose()
            print("✅ Startup order test passed")

            # Test 4: All streams consumable
            print("\n4️⃣ Testing all streams consumable...")
            fake_redis_4 = fakeredis.FakeAsyncRedis(decode_responses=True)
            await test_all_streams_have_consumers(fake_redis_4)
            await fake_redis_4.aclose()
            print("✅ All streams consumable test passed")

            # Test 5: Message handling
            print("\n5️⃣ Testing message handling...")
            fake_redis_5 = fakeredis.FakeAsyncRedis(decode_responses=True)
            await test_stream_creation_with_messages(fake_redis_5)
            await fake_redis_5.aclose()
            print("✅ Message handling test passed")

            # Test 6: Group id parameter
            print("\n6️⃣ Testing group id parameter...")
            fake_redis_6 = fakeredis.FakeAsyncRedis(decode_responses=True)
            await test_group_id_parameter(fake_redis_6)
            await fake_redis_6.aclose()
            print("✅ Group id parameter test passed")

            print("\n🎉 All tests passed!")

        except Exception as exc:
            print(f"\n❌ Test failed: {exc}")
            raise

    asyncio.run(run_tests())
