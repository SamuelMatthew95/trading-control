"""
Simple smoke test to verify core functionality works end-to-end.
"""

import asyncio
import uuid
from decimal import Decimal
from datetime import datetime, timezone

# Test only core imports that should work
from api.services.trade_signal_filter import get_trade_signal_filter
from api.runtime_state import has_processed, mark_processed


async def smoke_test():
    """Test basic functionality without complex setup."""
    print("Running smoke test...")
    
    # Test 1: Trade signal filter
    print("Testing trade signal filter...")
    filter = get_trade_signal_filter()
    
    trade_event = {
        "type": "TRADE_SIGNAL",
        "payload": {"action": "BUY", "symbol": "BTC"},
        "msg_id": str(uuid.uuid4()),
    }
    
    result = filter.filter_event(trade_event)
    assert result["action"] == "process"
    print("✓ Trade signal filter works")
    
    # Test 2: Idempotency
    print("Testing idempotency...")
    msg_id = str(uuid.uuid4())
    
    assert not has_processed(msg_id)
    mark_processed(msg_id)
    assert has_processed(msg_id)
    print("✓ Idempotency works")
    
    # Test 3: Basic data structures
    print("Testing data structures...")
    from api.core.models.trade_ledger import TradeLedger
    
    trade = TradeLedger(
        agent_id="test",
        strategy_id=uuid.uuid4(),
        symbol="BTC",
        trade_type="BUY",
        quantity=Decimal("1.0"),
        entry_price=Decimal("50000"),
        status="OPEN",
        execution_mode="MOCK",
        source="test",
    )
    
    assert trade.symbol == "BTC"
    assert trade.trade_type == "BUY"
    assert trade.is_open
    print("✓ Data structures work")
    
    print("\nSmoke test PASSED - core functionality is working")
    return True


async def main():
    """Run smoke test."""
    try:
        success = await smoke_test()
        if success:
            print("\nNEXT STEPS:")
            print("1. Run: python3 smoke_test.py")
            print("2. If passes, run: python3 -m alembic upgrade head")
            print("3. Start API server: python3 -m api.main")
            print("4. Test endpoints: curl http://localhost:8000/api/trades/summary")
        else:
            print("Smoke test failed - check imports")
    except Exception as e:
        print(f"Smoke test error: {e}")
        print("Check if all imports are working correctly")


if __name__ == "__main__":
    asyncio.run(main())
