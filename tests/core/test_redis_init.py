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
from api.events.bus import (
    DEFAULT_GROUP,
    PIPELINE_GROUP,
    STREAMS,
    EventBus,
    ensure_all_streams_ready,
)


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
        STREAM_AGENT_LOGS,
    }

    # Both DEFAULT_GROUP (agents) and PIPELINE_GROUP (broadcast pipeline) are created
    expected_groups = {DEFAULT_GROUP, PIPELINE_GROUP}

    for stream in expected_streams:
        groups = await fake_redis.xinfo_groups(stream)
        group_names = set()
        for g in groups:
            name = g["name"]
            if isinstance(name, bytes):
                name = name.decode()
            group_names.add(name)
        assert expected_groups <= group_names, (
            f"Stream {stream!r} missing groups: {expected_groups - group_names}"
        )


@pytest.mark.asyncio
async def test_idempotency_multiple_calls(fake_redis):
    """Test 2: Idempotency - calling twice doesn't crash."""
    # First call - should succeed
    event_bus = EventBus(fake_redis)
    await event_bus.create_groups()

    # Second call - should also succeed (BUSYGROUP handled silently)
    # This should not raise any exceptions
    await event_bus.create_groups()

    # Verify both groups still exist after idempotent second call
    for stream in STREAMS:
        groups = await fake_redis.xinfo_groups(stream)
        group_names = {
            (g["name"].decode() if isinstance(g["name"], bytes) else g["name"]) for g in groups
        }
        assert DEFAULT_GROUP in group_names, f"Stream {stream!r} missing DEFAULT_GROUP"
        assert PIPELINE_GROUP in group_names, f"Stream {stream!r} missing PIPELINE_GROUP"


@pytest.mark.asyncio
async def test_all_streams_have_consumers(fake_redis):
    """Test that all 7 streams can be consumed after initialization."""
    event_bus = EventBus(fake_redis)
    await event_bus.create_groups()

    # Test consuming from each stream
    for stream in STREAMS:
        try:
            messages = await event_bus.consume(stream, DEFAULT_GROUP, f"test_consumer_{stream}")
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
    message_id = await event_bus.publish("signals", {"signal": "BUY", "symbol": "ETH/USD"})
    assert message_id is not None

    # Try to consume - should get the message since group was created before
    messages = await event_bus.consume("signals", DEFAULT_GROUP, "test_consumer")

    # Should get the message because it was added after group creation
    assert len(messages) == 1
    msg_id, payload = messages[0]
    assert payload["signal"] == "BUY"


@pytest.mark.asyncio
async def test_nogroup_self_healing_in_consume(fake_redis):
    """NOGROUP during consume() triggers _ensure_stream_and_group and returns []."""
    event_bus = EventBus(fake_redis)
    await event_bus.create_groups()

    # Delete one stream entirely to force NOGROUP on next consume
    await fake_redis.delete(STREAM_ORDERS)

    # consume() must NOT raise; it should self-heal and return []
    result = await event_bus.consume(STREAM_ORDERS, DEFAULT_GROUP, "test_consumer")
    assert result == []

    # After self-healing, the stream/group must exist again
    groups = await fake_redis.xinfo_groups(STREAM_ORDERS)
    group_names = {
        (g["name"].decode() if isinstance(g["name"], bytes) else g["name"]) for g in groups
    }
    assert DEFAULT_GROUP in group_names, "DEFAULT_GROUP not recreated after NOGROUP in consume"


@pytest.mark.asyncio
async def test_nogroup_self_healing_in_reclaim(fake_redis):
    """NOGROUP during reclaim_stale() triggers _ensure_stream_and_group and returns []."""
    event_bus = EventBus(fake_redis)
    await event_bus.create_groups()

    # Delete one stream entirely to force NOGROUP on xautoclaim
    await fake_redis.delete(STREAM_AGENT_LOGS)

    # reclaim_stale() must NOT raise; it should self-heal and return []
    result = await event_bus.reclaim_stale(STREAM_AGENT_LOGS, DEFAULT_GROUP, "test_consumer")
    assert result == []

    # After self-healing, the stream/group must exist again
    groups = await fake_redis.xinfo_groups(STREAM_AGENT_LOGS)
    group_names = {
        (g["name"].decode() if isinstance(g["name"], bytes) else g["name"]) for g in groups
    }
    assert DEFAULT_GROUP in group_names, "DEFAULT_GROUP not recreated after NOGROUP in reclaim"


@pytest.mark.asyncio
async def test_ensure_all_streams_ready_cold_start(fake_redis):
    """ensure_all_streams_ready() creates all streams/groups on a completely empty Redis."""
    assert await fake_redis.dbsize() == 0

    await ensure_all_streams_ready(fake_redis)

    for stream in STREAMS:
        groups = await fake_redis.xinfo_groups(stream)
        group_names = {
            (g["name"].decode() if isinstance(g["name"], bytes) else g["name"]) for g in groups
        }
        assert DEFAULT_GROUP in group_names, f"{stream} missing DEFAULT_GROUP after cold start"
        assert PIPELINE_GROUP in group_names, f"{stream} missing PIPELINE_GROUP after cold start"


@pytest.mark.asyncio
async def test_ensure_all_streams_ready_idempotent(fake_redis):
    """Calling ensure_all_streams_ready() twice does not raise and groups survive."""
    await ensure_all_streams_ready(fake_redis)
    await ensure_all_streams_ready(fake_redis)  # second call must be safe

    for stream in STREAMS:
        groups = await fake_redis.xinfo_groups(stream)
        group_names = {
            (g["name"].decode() if isinstance(g["name"], bytes) else g["name"]) for g in groups
        }
        assert DEFAULT_GROUP in group_names
        assert PIPELINE_GROUP in group_names


@pytest.mark.asyncio
async def test_ensure_all_streams_ready_recovers_deleted_stream(fake_redis):
    """ensure_all_streams_ready() recreates a stream that was deleted at runtime."""
    await ensure_all_streams_ready(fake_redis)

    # Simulate runtime stream deletion
    await fake_redis.delete(STREAM_SIGNALS)
    await fake_redis.delete(STREAM_RISK_ALERTS)

    # Re-run barrier — must recover the deleted streams
    await ensure_all_streams_ready(fake_redis)

    for stream in (STREAM_SIGNALS, STREAM_RISK_ALERTS):
        groups = await fake_redis.xinfo_groups(stream)
        group_names = {
            (g["name"].decode() if isinstance(g["name"], bytes) else g["name"]) for g in groups
        }
        assert DEFAULT_GROUP in group_names, f"{stream} not recovered by ensure_all_streams_ready"
        assert PIPELINE_GROUP in group_names, f"{stream} not recovered by ensure_all_streams_ready"


@pytest.mark.asyncio
async def test_ensure_stream_and_group_is_idempotent(fake_redis):
    """_ensure_stream_and_group() is safe to call when group already exists (BUSYGROUP)."""
    event_bus = EventBus(fake_redis)
    await event_bus.create_groups()

    # Call _ensure_stream_and_group on an already-existing stream+group — must not raise
    await event_bus._ensure_stream_and_group(STREAM_MARKET_TICKS, DEFAULT_GROUP)
    await event_bus._ensure_stream_and_group(STREAM_MARKET_TICKS, PIPELINE_GROUP)

    # Groups must still exist
    groups = await fake_redis.xinfo_groups(STREAM_MARKET_TICKS)
    group_names = {
        (g["name"].decode() if isinstance(g["name"], bytes) else g["name"]) for g in groups
    }
    assert DEFAULT_GROUP in group_names
    assert PIPELINE_GROUP in group_names


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
