#!/usr/bin/env python3
"""Test API endpoints in memory mode."""

import asyncio
import sys

sys.path.insert(0, '.')

async def test_api():
    """Test API endpoints in memory mode."""
    from fastapi.testclient import TestClient

    from api.main import app
    from api.runtime_state import set_db_available, set_persistence_mode

    # Set memory mode
    set_db_available(False)
    set_persistence_mode('memory')

    # Create test client
    client = TestClient(app)

    print('Testing API endpoints in memory mode...')

    # Test health
    try:
        response = client.get('/api/health')
        print(f'Health: {response.status_code}')
        if response.status_code == 200:
            data = response.json()
            print(f'  DB available: {data.get("db_available", "unknown")}')
            print(f'  Mode: {data.get("mode", "unknown")}')
    except Exception as e:
        print(f'Health failed: {e}')

    # Test dashboard state
    try:
        response = client.get('/api/dashboard/state')
        print(f'Dashboard state: {response.status_code}')
        if response.status_code == 200:
            data = response.json()
            print(f'  Mode: {data.get("mode", "unknown")}')
            print(f'  Persistence: {data.get("persistence_mode", "unknown")}')
    except Exception as e:
        print(f'Dashboard state failed: {e}')

    print('API testing complete')

if __name__ == '__main__':
    asyncio.run(test_api())
