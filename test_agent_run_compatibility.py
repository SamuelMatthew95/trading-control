#!/usr/bin/env python3
"""Test script for AgentRun production and test compatibility"""

from api.core.models import AgentRun
from tests.test_agent_run_utils import TestAgentRun, create_test_agent_run

def test_production_agent_run():
    """Test production AgentRun model (clean, no legacy fields)"""
    try:
        run = AgentRun(strategy_id='momentum_v1', symbol='AAPL', trace_id='trace_123')
        print('✓ PASS: Production AgentRun works with clean schema')
        print(f'  - strategy_id: {run.strategy_id}')
        print(f'  - symbol: {run.symbol}')
        print(f'  - trace_id: {run.trace_id}')
        
        # Verify legacy fields are not present
        try:
            decision_json = run.decision_json
            print('✗ FAIL: decision_json should not exist in production model')
            return False
        except AttributeError:
            print('✓ PASS: decision_json correctly removed from production model')
            return True
            
    except Exception as e:
        print(f'✗ FAIL: {e}')
        return False

def test_agent_run_compatibility():
    """Test TestAgentRun compatibility with legacy fields"""
    try:
        # Test direct instantiation
        run1 = TestAgentRun(task_id='test_task', decision_json='{}', trace_json='[]', trace_id='trace_123')
        print('✓ PASS: TestAgentRun works with legacy fields')
        print(f'  - task_id: {run1.task_id}')
        print(f'  - decision_json: {run1.decision_json}')
        print(f'  - trace_json: {run1.trace_json}')
        
        # Test factory function
        run2 = create_test_agent_run(
            task_id='factory_task',
            decision_json='{"action": "buy"}',
            trace_json='[{"step": "analyze"}]',
            strategy_id='momentum_v1',
            symbol='AAPL'
        )
        print('✓ PASS: Factory function works')
        print(f'  - task_id: {run2.task_id}')
        print(f'  - strategy_id: {run2.strategy_id}')
        print(f'  - symbol: {run2.symbol}')
        print(f'  - decision_json: {run2.decision_json}')
        print(f'  - trace_json: {run2.trace_json}')
        
        return True
        
    except Exception as e:
        print(f'✗ FAIL: {e}')
        return False

if __name__ == '__main__':
    print("=== Testing AgentRun Production and Test Compatibility ===")
    
    prod_ok = test_production_agent_run()
    test_ok = test_agent_run_compatibility()
    
    if prod_ok and test_ok:
        print("\n🎉 ALL TESTS PASSED!")
        print("✅ Production AgentRun model is clean")
        print("✅ TestAgentRun provides backward compatibility")
        print("✅ Ready for CI/CD deployment")
    else:
        print("\n❌ SOME TESTS FAILED!")
        print("🔧 Check the errors above")
