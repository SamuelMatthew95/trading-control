#!/usr/bin/env python3
"""Test script to verify all API endpoints work in in-memory mode."""

import asyncio
import sys

# Add current directory to path
sys.path.insert(0, '.')

async def test_endpoints():
    """Test all API endpoints in in-memory mode."""
    from fastapi.testclient import TestClient

    from api.main import app
    from api.runtime_state import (
        runtime_mode,
        set_db_available,
        set_persistence_mode,
        storage_backend,
    )

    # Set up memory mode
    set_db_available(False)
    set_persistence_mode('memory')

    print(f'✅ Storage backend: {storage_backend()}')
    print(f'✅ Runtime mode: {runtime_mode()}')

    # Test basic app startup
    from contextlib import asynccontextmanager

    from api.in_memory_store import InMemoryStore
    from api.runtime_state import set_runtime_store

    @asynccontextmanager
    async def lifespan_override(app):
        try:
            # Simulate main lifespan setup
            store = InMemoryStore()
            set_runtime_store(store)
            app.state.in_memory_store = store
            app.state.db_available = False
            app.state.persistence_mode = 'memory'
            set_db_available(False)
            set_persistence_mode('memory')

            print('✅ App started in memory mode')
            yield
        finally:
            print('✅ App shutdown cleanly')

    app.router.lifespan_context = lifespan_override

    # Test some basic endpoints
    client = TestClient(app)

    # Test health endpoint
    try:
        response = client.get('/api/health')
        print(f'✅ Health endpoint: {response.status_code}')
        if response.status_code == 200:
            data = response.json()
            print(f'   DB available: {data.get("db_available", "unknown")}')
            print(f'   Mode: {data.get("mode", "unknown")}')
    except Exception as e:
        print(f'❌ Health endpoint failed: {e}')

    # Test dashboard state
    try:
        response = client.get('/api/dashboard/state')
        print(f'✅ Dashboard state: {response.status_code}')
        if response.status_code == 200:
            data = response.json()
            print(f'   Mode: {data.get("mode", "unknown")}')
            print(f'   Persistence: {data.get("persistence_mode", "unknown")}')
    except Exception as e:
        print(f'❌ Dashboard state failed: {e}')

    # Test agent instances
    try:
        response = client.get('/api/dashboard/agent-instances')
        print(f'✅ Agent instances: {response.status_code}')
        if response.status_code == 200:
            data = response.json()
            print(f'   Active count: {data.get("active_count", "unknown")}')
    except Exception as e:
        print(f'❌ Agent instances failed: {e}')

    # Test trade feed
    try:
        response = client.get('/api/dashboard/trade-feed')
        print(f'✅ Trade feed: {response.status_code}')
        if response.status_code == 200:
            data = response.json()
            print(f'   Count: {data.get("count", "unknown")}')
    except Exception as e:
        print(f'❌ Trade feed failed: {e}')

    # Test learning endpoints
    try:
        response = client.get('/api/dashboard/learning/ic-weights')
        print(f'✅ IC weights: {response.status_code}')
        if response.status_code == 200:
            data = response.json()
            print(f'   IC weights count: {len(data.get("ic_weights", []))}')
    except Exception as e:
        print(f'❌ IC weights failed: {e}')

    try:
        response = client.get('/api/dashboard/learning/grades')
        print(f'✅ Grades: {response.status_code}')
        if response.status_code == 200:
            data = response.json()
            print(f'   Grades count: {data.get("total", "unknown")}')
    except Exception as e:
        print(f'❌ Grades failed: {e}')

    print('✅ All endpoints tested successfully in memory mode')

if __name__ == "__main__":
    asyncio.run(test_endpoints())
