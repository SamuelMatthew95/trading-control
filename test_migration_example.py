"""
Example: How to update existing tests to use TestAgentRun

This file demonstrates the migration path for existing tests that currently
use AgentRun with legacy fields (decision_json, trace_json, task_id).

BEFORE (causes errors):
    from api.core.models import AgentRun
    
    run = AgentRun(
        task_id="consensus:run-2",
        decision_json="{}",
        trace_json="[]",
        trace_id="trace_123"
    )
    # TypeError: 'decision_json' is an invalid keyword argument for AgentRun

AFTER (works perfectly):
    from tests.test_agent_run_utils import TestAgentRun, create_test_agent_run
    
    # Option 1: Direct instantiation with TestAgentRun
    run = TestAgentRun(
        task_id="consensus:run-2",
        decision_json="{}",
        trace_json="[]",
        trace_id="trace_123"
    )
    
    # Option 2: Use factory function (recommended)
    run = create_test_agent_run(
        task_id="consensus:run-2",
        decision_json="{}",
        trace_json="[]",
        trace_id="trace_123"
    )
    
    # Option 3: With production fields
    run = create_test_agent_run(
        task_id="consensus:run-2",
        decision_json='{"action": "buy", "confidence": 0.8}',
        trace_json='[{"step": "analyze", "result": "bullish"}]',
        trace_id="trace_123",
        strategy_id="momentum_v1",
        symbol="AAPL",
        action="buy",
        confidence=0.8
    )

Migration Strategy:
1. Replace 'from api.core.models import AgentRun' with 'from tests.test_agent_run_utils import TestAgentRun, create_test_agent_run'
2. Replace 'AgentRun(' with 'create_test_agent_run(' (recommended) or 'TestAgentRun('
3. All existing test code continues to work without changes
4. Production schema remains clean and focused

Benefits:
- ✅ Production schema stays clean (no test-only fields)
- ✅ Existing tests work without modification
- ✅ Gradual migration path available
- ✅ Cross-database compatibility maintained
- ✅ Clear separation of test vs production concerns
"""

import asyncio
from tests.test_agent_run_utils import TestAgentRun, create_test_agent_run, FakeSession, FakeSessionFactory


async def example_test_usage():
    """Example showing how to use TestAgentRun in tests"""
    
    # Example 1: Basic test instantiation (what most existing tests need)
    run = TestAgentRun(
        task_id="consensus:run-2",
        decision_json="{}",
        trace_json="[]",
        trace_id="trace_123"
    )
    
    # Example 2: Using factory function (recommended approach)
    run = create_test_agent_run(
        task_id="consensus:run-2",
        decision_json='{"action": "buy", "confidence": 0.8}',
        trace_json='[{"step": "analyze", "result": "bullish"}]',
        trace_id="trace_123",
        strategy_id="momentum_v1",
        symbol="AAPL"
    )
    
    # Example 3: Testing with FakeSession and async transactions
    session = FakeSession()
    
    async with session.begin():
        # Simulate database operations
        await session.execute("INSERT INTO agent_runs (...) VALUES (...)")
        
        # Create test AgentRun within transaction
        run = create_test_agent_run(
            task_id="transaction_test",
            decision_json='{"action": "sell"}',
            trace_json='[]',
            trace_id="trace_456"
        )
        
        # Access both legacy and production fields
        assert run.decision_json == '{"action": "sell"}'
        assert run.strategy_id is None  # Not set in this example
        assert run.trace_id == "trace_456"
    
    print("✅ Example test usage works perfectly!")
    return True


if __name__ == '__main__':
    print("=== Example Test Usage Demonstration ===")
    asyncio.run(example_test_usage())
