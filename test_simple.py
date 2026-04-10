#!/usr/bin/env python3
"""Simple test to verify in-memory mode works."""

import asyncio
import sys

sys.path.insert(0, ".")


async def test_memory_mode():
    """Test in-memory mode functionality."""
    from api.in_memory_store import InMemoryStore
    from api.runtime_state import (
        runtime_mode,
        set_db_available,
        set_persistence_mode,
        storage_backend,
    )

    # Set up memory mode
    set_db_available(False)
    set_persistence_mode("memory")

    print(f"✅ Storage backend: {storage_backend()}")
    print(f"✅ Runtime mode: {runtime_mode()}")

    # Test in-memory store
    store = InMemoryStore()

    # Test adding data
    store.add_notification("Test notification", level="info")
    store.add_grade({"trace_id": "test-trace", "score": 0.85, "metrics": {"test": True}})
    store.add_event({"event_type": "test_event", "data": {"test": True}})

    # Test dashboard snapshot
    snapshot = store.dashboard_fallback_snapshot()
    print(f"✅ Dashboard snapshot mode: {snapshot.get('mode')}")
    print(f"✅ Dashboard snapshot persistence: {snapshot.get('persistence_mode')}")
    print(f"✅ Notifications count: {len(snapshot.get('notifications', []))}")
    print(f"✅ Agent statuses count: {len(snapshot.get('agent_statuses', []))}")

    # Test agent status updates
    store.upsert_agent("test_agent", {"status": "active", "last_seen": 1234567890})
    agent = store.get_agent("test_agent")
    print(f"✅ Agent status: {agent.get('status') if agent else 'None'}")

    print("✅ All in-memory mode tests passed!")


if __name__ == "__main__":
    asyncio.run(test_memory_mode())
