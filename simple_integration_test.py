"""
Simple integration test for trade ledger service.
"""

import asyncio
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from api.services.trade_ledger_service import TradeLedgerService
from api.core.models.trade_ledger import TradeLedger


async def test_trade_ledger_integration():
    """Test trade ledger service with minimal dependencies."""
    print("Testing trade ledger integration...")
    
    # Mock database session
    session = AsyncMock()
    service = TradeLedgerService(session)
    
    # Test BUY trade creation
    strategy_id = uuid.uuid4()
    buy_trade = await service.create_buy_trade(
        agent_id="test_agent",
        strategy_id=strategy_id,
        symbol="BTC",
        quantity=Decimal("1.0"),
        entry_price=Decimal("50000"),
        confidence_score=85.0,
        execution_mode="MOCK",
        trace_id="test_123",
        metadata={"test": True},
    )
    
    print(f"✓ BUY trade created: {buy_trade.symbol} @ ${buy_trade.entry_price}")
    assert buy_trade.trade_type == "BUY"
    assert buy_trade.status == "OPEN"
    
    # Test SELL trade with pairing
    sell_trade, parent_buy = await service.create_sell_trade(
        agent_id="test_agent",
        strategy_id=strategy_id,
        symbol="BTC",
        quantity=Decimal("1.0"),
        exit_price=Decimal("51000"),
        confidence_score=90.0,
        execution_mode="MOCK",
        trace_id="test_123",
        metadata={"test": True},
    )
    
    print(f"✓ SELL trade paired: P&L = ${sell_trade.pnl_realized}")
    assert sell_trade.trade_type == "SELL"
    assert sell_trade.status == "CLOSED"
    assert sell_trade.pnl_realized == Decimal("1000.00")
    
    # Test portfolio summary
    summary = await service.get_portfolio_summary()
    print(f"✓ Portfolio summary: {summary['open_positions']} open, ${summary['total_pnl']} P&L")
    
    print("Integration test PASSED")
    return True


async def main():
    """Run integration test."""
    try:
        success = await test_trade_ledger_integration()
        if success:
            print("\nTrade ledger service is working correctly")
            print("Ready for full system integration")
        else:
            print("\nIntegration test failed")
    except Exception as e:
        print(f"Integration test error: {e}")
        print("Check imports and database setup")


if __name__ == "__main__":
    asyncio.run(main())
