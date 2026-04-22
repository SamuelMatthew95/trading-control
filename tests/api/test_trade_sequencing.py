"""Tests for trade sequencing chronological ordering and session boundaries."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from api.routes.dashboard_v2 import get_trade_feed, _in_memory_trade_feed_payload
from api.runtime_state import get_runtime_store, set_db_available


@pytest.mark.asyncio
async def test_trade_feed_chronological_ordering_db_mode():
    """Test that trade feed returns trades in chronological order in DB mode."""
    
    # Mock database mode
    with patch('api.routes.dashboard_v2.is_db_available', return_value=True):
        with patch('api.routes.dashboard_v2.AsyncSessionFactory') as mock_session_factory:
            # Create mock session
            mock_session = AsyncMock()
            mock_session_factory.return_value.__aenter__.return_value = mock_session
            mock_session_factory.return_value.__aexit__.return_value = None
            
            # Mock database response with trades in chronological order
            mock_rows = [
                (
                    "trade1", "TSLA", "buy", 1.0, 380.0, 385.0, 5.0, 1.31, "order1", 
                    "trace1", "signal1", "A", 85.0, "Excellent", "completed",
                    datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 10, 1, tzinfo=timezone.utc),
                    None, datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)  # session_date
                ),
                (
                    "trade2", "TSLA", "sell", 1.0, 385.0, 382.0, -3.0, -0.78, "order2",
                    "trace2", "signal2", "B", 75.0, "Good", "completed",
                    datetime(2024, 1, 1, 10, 2, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 10, 3, tzinfo=timezone.utc),
                    None, datetime(2024, 1, 1, 10, 2, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 10, 2, tzinfo=timezone.utc)  # session_date
                ),
                (
                    "trade3", "AAPL", "buy", 2.0, 150.0, 155.0, 10.0, 3.33, "order3",
                    "trace3", "signal3", "A", 90.0, "Excellent", "completed",
                    datetime(2024, 1, 1, 10, 4, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 10, 5, tzinfo=timezone.utc),
                    None, datetime(2024, 1, 1, 10, 4, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 10, 4, tzinfo=timezone.utc)  # session_date
                ),
            ]
            
            mock_result = AsyncMock()
            mock_result.all.return_value = mock_rows
            mock_session.execute.return_value = mock_result
            
            # Call the endpoint
            result = await get_trade_feed(limit=50)
            
            # Verify chronological ordering
            trades = result["trades"]
            assert len(trades) == 3
            assert trades[0]["id"] == "trade1"  # Oldest first
            assert trades[1]["id"] == "trade2"
            assert trades[2]["id"] == "trade3"  # Newest last
            assert result["chronological"] is True


@pytest.mark.asyncio
async def test_trade_feed_session_boundaries():
    """Test that session boundaries are properly included in trade feed."""
    
    with patch('api.routes.dashboard_v2.is_db_available', return_value=True):
        with patch('api.routes.dashboard_v2.AsyncSessionFactory') as mock_session_factory:
            mock_session = AsyncMock()
            mock_session_factory.return_value.__aenter__.return_value = mock_session
            mock_session_factory.return_value.__aexit__.return_value = None
            
            # Mock trades from different sessions
            mock_rows = [
                (
                    "trade1", "TSLA", "buy", 1.0, 380.0, 385.0, 5.0, 1.31, "order1",
                    "trace1", "signal1", "A", 85.0, "Excellent", "completed",
                    datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 10, 1, tzinfo=timezone.utc),
                    None, datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)  # session_date
                ),
                (
                    "trade2", "TSLA", "sell", 1.0, 385.0, 382.0, -3.0, -0.78, "order2",
                    "trace2", "signal2", "B", 75.0, "Good", "completed",
                    datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc),  # Different day
                    datetime(2024, 1, 2, 10, 1, tzinfo=timezone.utc),
                    None, datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)  # session_date
                ),
            ]
            
            mock_result = AsyncMock()
            mock_result.all.return_value = mock_rows
            mock_session.execute.return_value = mock_result
            
            result = await get_trade_feed(limit=50)
            
            # Verify session dates are included
            trades = result["trades"]
            assert len(trades) == 2
            assert trades[0]["session_date"] == "2024-01-01"
            assert trades[1]["session_date"] == "2024-01-02"


@pytest.mark.asyncio
async def test_in_memory_trade_feed_chronological_ordering():
    """Test that in-memory trade feed returns trades in chronological order."""
    
    # Set up in-memory mode
    set_db_available(False)
    store = get_runtime_store()
    
    # Clear existing trades
    store.trade_feed.clear()
    
    # Add trades in chronological order (simulating real-time additions)
    trades_data = [
        {
            "id": "trade1",
            "symbol": "TSLA",
            "side": "buy",
            "qty": 1.0,
            "entry_price": 380.0,
            "exit_price": 385.0,
            "pnl": 5.0,
            "created_at": datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc).timestamp(),
        },
        {
            "id": "trade2",
            "symbol": "TSLA", 
            "side": "sell",
            "qty": 1.0,
            "entry_price": 380.0,
            "exit_price": 382.0,
            "pnl": -3.0,
            "created_at": datetime(2024, 1, 1, 10, 2, tzinfo=timezone.utc).timestamp(),
        },
        {
            "id": "trade3",
            "symbol": "AAPL",
            "side": "buy",
            "qty": 2.0,
            "entry_price": 150.0,
            "exit_price": 155.0,
            "pnl": 10.0,
            "created_at": datetime(2024, 1, 1, 10, 4, tzinfo=timezone.utc).timestamp(),
        },
    ]
    
    for trade in trades_data:
        store.upsert_trade_fill(trade)
    
    # Test in-memory trade feed payload
    result = _in_memory_trade_feed_payload(limit=50)
    
    # Verify chronological ordering
    trades = result["trades"]
    assert len(trades) == 3
    assert trades[0]["id"] == "trade1"  # Oldest first
    assert trades[1]["id"] == "trade2"
    assert trades[2]["id"] == "trade3"  # Newest last
    assert result["chronological"] is True
    assert result["source"] == "in_memory"


@pytest.mark.asyncio
async def test_trade_feed_buy_before_sell_sequence():
    """Test that trades follow proper BUY before SELL sequence within sessions."""
    
    with patch('api.routes.dashboard_v2.is_db_available', return_value=True):
        with patch('api.routes.dashboard_v2.AsyncSessionFactory') as mock_session_factory:
            mock_session = AsyncMock()
            mock_session_factory.return_value.__aenter__.return_value = mock_session
            
            # Mock proper sequence: BUY -> SELL -> BUY -> SELL
            mock_rows = [
                (
                    "trade1", "TSLA", "buy", 1.0, 380.0, None, None, None, "order1",
                    "trace1", "signal1", None, None, None, "completed",
                    datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                    None, None, datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
                ),
                (
                    "trade2", "TSLA", "sell", 1.0, 380.0, 385.0, 5.0, 1.31, "order2",
                    "trace2", "signal2", "A", 85.0, "Excellent", "completed",
                    datetime(2024, 1, 1, 10, 2, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 10, 3, tzinfo=timezone.utc),
                    None, datetime(2024, 1, 1, 10, 2, tzinfo=timezone.utc)
                ),
                (
                    "trade3", "TSLA", "buy", 2.0, 382.0, None, None, None, "order3",
                    "trace3", "signal3", None, None, None, "completed",
                    datetime(2024, 1, 1, 10, 4, tzinfo=timezone.utc),
                    None, None, datetime(2024, 1, 1, 10, 4, tzinfo=timezone.utc)
                ),
                (
                    "trade4", "TSLA", "sell", 2.0, 382.0, 378.0, -8.0, -1.05, "order4",
                    "trace4", "signal4", "C", 65.0, "Fair", "completed",
                    datetime(2024, 1, 1, 10, 6, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 10, 7, tzinfo=timezone.utc),
                    None, datetime(2024, 1, 1, 10, 6, tzinfo=timezone.utc)
                ),
            ]
            
            mock_result = AsyncMock()
            mock_result.all.return_value = mock_rows
            mock_session.execute.return_value = mock_result
            
            result = await get_trade_feed(limit=50)
            
            # Verify proper sequence
            trades = result["trades"]
            assert len(trades) == 4
            assert trades[0]["side"] == "buy"   # First trade is BUY
            assert trades[1]["side"] == "sell"  # Then SELL
            assert trades[2]["side"] == "buy"   # Then BUY
            assert trades[3]["side"] == "sell"  # Then SELL


@pytest.mark.asyncio
async def test_trade_feed_limit_respects_chronological_order():
    """Test that limit parameter works correctly while maintaining chronological order."""
    
    set_db_available(False)
    store = get_runtime_store()
    store.trade_feed.clear()
    
    # Add 10 trades
    for i in range(10):
        trade = {
            "id": f"trade{i+1}",
            "symbol": "TSLA",
            "side": "buy" if i % 2 == 0 else "sell",
            "qty": 1.0,
            "created_at": (datetime(2024, 1, 1, 10, i, tzinfo=timezone.utc)).timestamp(),
        }
        store.upsert_trade_fill(trade)
    
    # Test with limit of 5
    result = _in_memory_trade_feed_payload(limit=5)
    
    # Should return the 5 most recent trades in chronological order
    trades = result["trades"]
    assert len(trades) == 5
    assert trades[0]["id"] == "trade6"  # 6th trade (oldest in result)
    assert trades[4]["id"] == "trade10" # 10th trade (newest in result)
