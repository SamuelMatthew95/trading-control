#!/usr/bin/env python3
"""Test script for FakeSession async context manager support"""

import asyncio
from tests.test_agent_run_utils import FakeSession, FakeSessionFactory

async def test_fake_session_async():
    """Test FakeSession with async context manager and begin()"""
    try:
        # Create a simple handler
        async def handler(sql, params):
            return FakeSession.FakeResult()
        
        session = FakeSession(handler)
        
        # Test async with session.begin()
        async with session.begin():
            await session.execute('SELECT 1')
        
        print('✓ PASS: FakeSession.begin() works with async context manager')
        print(f'  - Executed queries: {len(session.executed)}')
        print(f'  - Commits: {session.commits}')
        
        # Test regular async context
        async with session:
            await session.execute('SELECT 2')
        
        print('✓ PASS: FakeSession async context manager works')
        print(f'  - Total executed queries: {len(session.executed)}')
        
        return True
        
    except Exception as e:
        print(f'✗ FAIL: {e}')
        return False

async def test_fake_session_factory():
    """Test FakeSessionFactory"""
    try:
        factory = FakeSessionFactory()
        session = factory()
        
        async with session.begin():
            await session.execute('SELECT 3')
        
        print('✓ PASS: FakeSessionFactory works')
        print(f'  - Session type: {type(session).__name__}')
        
        return True
        
    except Exception as e:
        print(f'✗ FAIL: {e}')
        return False

if __name__ == '__main__':
    print("=== Testing FakeSession Async Context Manager ===")
    
    async def main():
        session_ok = await test_fake_session_async()
        factory_ok = await test_fake_session_factory()
        
        if session_ok and factory_ok:
            print("\n🎉 ALL FAKESESSION TESTS PASSED!")
            print("✅ FakeSession supports async context managers")
            print("✅ FakeSession.begin() works for transactions")
            print("✅ FakeSessionFactory works correctly")
            print("✅ Ready for CI/CD async testing")
        else:
            print("\n❌ SOME FAKESESSION TESTS FAILED!")
            print("🔧 Check the errors above")
    
    asyncio.run(main())
