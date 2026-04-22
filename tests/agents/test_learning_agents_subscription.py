"""Tests for learning agents subscription and event reception."""

import pytest
from unittest.mock import AsyncMock, patch
from api.services.agents.pipeline_agents import GradeAgent, ICUpdater, ReflectionAgent, StrategyProposer
from api.events.bus import EventBus
from api.events.dlq import DLQManager
from api.constants import (
    STREAM_EXECUTIONS, STREAM_TRADE_PERFORMANCE, STREAM_AGENT_GRADES, 
    STREAM_FACTOR_IC_HISTORY, STREAM_REFLECTION_OUTPUTS
)


@pytest.mark.asyncio
async def test_grade_agent_subscription_logging():
    """Test that GradeAgent logs its subscription to correct streams."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    
    with patch('api.services.agents.pipeline_agents.log_structured') as mock_log:
        grade_agent = GradeAgent(mock_bus, mock_dlq)
        
        # Verify subscription logging was called
        mock_log.assert_called_with("info", "grade_agent_subscribed", 
                                   streams=[STREAM_EXECUTIONS, STREAM_TRADE_PERFORMANCE])


@pytest.mark.asyncio
async def test_ic_updater_subscription_logging():
    """Test that ICUpdater logs its subscription to correct streams."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    mock_redis = AsyncMock()
    
    with patch('api.services.agents.pipeline_agents.log_structured') as mock_log:
        ic_updater = ICUpdater(mock_bus, mock_dlq, mock_redis)
        
        # Verify subscription logging was called
        mock_log.assert_called_with("info", "ic_updater_subscribed", 
                                   streams=[STREAM_TRADE_PERFORMANCE])


@pytest.mark.asyncio
async def test_reflection_agent_subscription_logging():
    """Test that ReflectionAgent logs its subscription to correct streams."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    
    with patch('api.services.agents.pipeline_agents.log_structured') as mock_log:
        reflection_agent = ReflectionAgent(mock_bus, mock_dlq)
        
        # Verify subscription logging was called
        mock_log.assert_called_with("info", "reflection_agent_subscribed", 
                                   streams=[STREAM_TRADE_PERFORMANCE, STREAM_AGENT_GRADES, STREAM_FACTOR_IC_HISTORY])


@pytest.mark.asyncio
async def test_strategy_proposer_subscription_logging():
    """Test that StrategyProposer logs its subscription to correct streams."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    
    with patch('api.services.agents.pipeline_agents.log_structured') as mock_log:
        strategy_proposer = StrategyProposer(mock_bus, mock_dlq)
        
        # Verify subscription logging was called
        mock_log.assert_called_with("info", "strategy_proposer_subscribed", 
                                   streams=[STREAM_REFLECTION_OUTPUTS])


@pytest.mark.asyncio
async def test_grade_agent_event_reception_logging():
    """Test that GradeAgent logs received events correctly."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    
    with patch('api.services.agents.pipeline_agents.log_structured') as mock_log:
        grade_agent = GradeAgent(mock_bus, mock_dlq)
        
        # Mock trade performance event
        trade_event = {
            FieldName.PNL: 5.25,
            FieldName.TRACE_ID: "trace-trade-123",
            "symbol": "TSLA",
        }
        
        await grade_agent.process(STREAM_TRADE_PERFORMANCE, "redis-id-123", trade_event)
        
        # Verify event reception logging was called
        mock_log.assert_any_call("info", "grade_agent_received_event", 
                                stream=STREAM_TRADE_PERFORMANCE, 
                                redis_id="redis-id-123", 
                                trace_id="trace-trade-123")


@pytest.mark.asyncio
async def test_ic_updater_event_reception_logging():
    """Test that ICUpdater logs received events correctly."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    mock_redis = AsyncMock()
    
    with patch('api.services.agents.pipeline_agents.log_structured') as mock_log:
        ic_updater = ICUpdater(mock_bus, mock_dlq, mock_redis)
        
        # Mock trade performance event
        trade_event = {
            FieldName.PNL: -2.15,
            FieldName.TRACE_ID: "trace-trade-456",
            "symbol": "AAPL",
        }
        
        await ic_updater.process(STREAM_TRADE_PERFORMANCE, "redis-id-456", trade_event)
        
        # Verify event reception logging was called
        mock_log.assert_called_with("info", "ic_updater_received_event", 
                                   stream=STREAM_TRADE_PERFORMANCE, 
                                   redis_id="redis-id-456", 
                                   trace_id="trace-trade-456")


@pytest.mark.asyncio
async def test_reflection_agent_event_reception_logging():
    """Test that ReflectionAgent logs received events correctly."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    
    with patch('api.services.agents.pipeline_agents.log_structured') as mock_log:
        reflection_agent = ReflectionAgent(mock_bus, mock_dlq)
        
        # Mock trade performance event
        trade_event = {
            FieldName.PNL: 3.75,
            FieldName.TRACE_ID: "trace-trade-789",
            "symbol": "ETH/USD",
        }
        
        await reflection_agent.process(STREAM_TRADE_PERFORMANCE, "redis-id-789", trade_event)
        
        # Verify event reception logging was called
        mock_log.assert_called_with("info", "reflection_agent_received_event", 
                                   stream=STREAM_TRADE_PERFORMANCE, 
                                   redis_id="redis-id-789", 
                                   trace_id="trace-trade-789")


@pytest.mark.asyncio
async def test_learning_agents_multiple_event_types():
    """Test that learning agents can handle different event types."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    
    with patch('api.services.agents.pipeline_agents.log_structured') as mock_log:
        reflection_agent = ReflectionAgent(mock_bus, mock_dlq)
        
        # Test different event types
        events = [
            (STREAM_TRADE_PERFORMANCE, {
                FieldName.PNL: 5.0,
                FieldName.TRACE_ID: "trace-trade-1",
                "symbol": "TSLA",
            }),
            (STREAM_AGENT_GRADES, {
                FieldName.GRADE: "A",
                FieldName.SCORE: 85.0,
                FieldName.TRACE_ID: "trace-grade-1",
            }),
            (STREAM_FACTOR_IC_HISTORY, {
                "factor_name": "momentum",
                "ic_score": 0.15,
                FieldName.TRACE_ID: "trace-ic-1",
            }),
        ]
        
        for stream, event_data in events:
            await reflection_agent.process(stream, f"redis-id-{stream}", event_data)
        
        # Verify all events were logged
        event_log_calls = [call for call in mock_log.call_args_list 
                         if "reflection_agent_received_event" in str(call)]
        assert len(event_log_calls) == 3
        
        # Verify correct streams were logged
        logged_streams = [call[1]["stream"] for call in event_log_calls]
        assert STREAM_TRADE_PERFORMANCE in logged_streams
        assert STREAM_AGENT_GRADES in logged_streams
        assert STREAM_FACTOR_IC_HISTORY in logged_streams


@pytest.mark.asyncio
async def test_grade_agent_processes_trade_performance_events():
    """Test that GradeAgent correctly processes trade performance events."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    
    grade_agent = GradeAgent(mock_bus, mock_dlq)
    
    # Mock multiple trade performance events
    trade_events = [
        {FieldName.PNL: 5.0, FieldName.TRACE_ID: "trace-1"},
        {FieldName.PNL: -2.0, FieldName.TRACE_ID: "trace-2"},
        {FieldName.PNL: 3.5, FieldName.TRACE_ID: "trace-3"},
    ]
    
    with patch.object(grade_agent, '_compute_and_publish_grade') as mock_grade:
        with patch('api.services.agents.pipeline_agents.settings', GRADE_EVERY_N_FILLS="3"):
            
            for event in trade_events:
                await grade_agent.process(STREAM_TRADE_PERFORMANCE, f"redis-id-{event[FieldName.TRACE_ID]}", event)
            
            # Verify grade computation was triggered after 3 fills
            mock_grade.assert_called_once()
            
            # Verify PnL buffer contains all trade PnL values
            assert len(grade_agent._pnl_buffer) == 3
            assert 5.0 in grade_agent._pnl_buffer
            assert -2.0 in grade_agent._pnl_buffer
            assert 3.5 in grade_agent._pnl_buffer


@pytest.mark.asyncio
async def test_ic_updater_processes_trade_performance_events():
    """Test that ICUpdater correctly processes trade performance events."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    mock_redis = AsyncMock()
    
    ic_updater = ICUpdater(mock_bus, mock_dlq, mock_redis)
    
    # Mock trade performance events
    trade_events = [
        {FieldName.PNL: 2.5, FieldName.TRACE_ID: "trace-1"},
        {FieldName.PNL: -1.0, FieldName.TRACE_ID: "trace-2"},
    ]
    
    with patch.object(ic_updater, '_fetch_composite_score', return_value=0.75):
        with patch.object(ic_updater, '_recompute_and_publish') as mock_recompute:
            with patch('api.services.agents.pipeline_agents.settings', IC_UPDATE_EVERY_N_FILLS="2"):
                
                for event in trade_events:
                    await ic_updater.process(STREAM_TRADE_PERFORMANCE, f"redis-id-{event[FieldName.TRACE_ID]}", event)
                
                # Verify IC recomputation was triggered after 2 fills
                mock_recompute.assert_called_once()
                
                # Verify score-pnl buffer contains correct data
                assert len(ic_updater._score_pnl_buffer) == 2
                assert (0.75, 2.5) in ic_updater._score_pnl_buffer
                assert (0.75, -1.0) in ic_updater._score_pnl_buffer


@pytest.mark.asyncio
async def test_reflection_agent_accumulates_trade_data():
    """Test that ReflectionAgent accumulates trade data correctly."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    
    reflection_agent = ReflectionAgent(mock_bus, mock_dlq)
    
    # Mock trade performance events
    trade_events = [
        {
            FieldName.SYMBOL: "TSLA",
            FieldName.SIDE: "buy",
            FieldName.PNL: 5.0,
            FieldName.PNL_PERCENT: 1.31,
            FieldName.FILL_PRICE: 380.0,
            FieldName.FILLED_AT: "2024-01-01T10:00:00Z",
            FieldName.TRACE_ID: "trace-1",
        },
        {
            FieldName.SYMBOL: "AAPL",
            FieldName.SIDE: "sell",
            FieldName.PNL: -2.0,
            FieldName.PNL_PERCENT: -0.52,
            FieldName.FILL_PRICE: 155.0,
            FieldName.FILLED_AT: "2024-01-01T10:02:00Z",
            FieldName.TRACE_ID: "trace-2",
        },
        {
            FieldName.LOG_TYPE: LogType.IC_UPDATE,
            FieldName.TRACE_ID: "ic-1",
            FieldName.TIMESTAMP: time.time(),
        },
    ]
    
    with patch.object(reflection_agent, '_run_reflection') as mock_reflection:
        with patch('api.services.agents.pipeline_agents.settings', REFLECT_EVERY_N_FILLS="2"):
            
            for event in trade_events:
                await reflection_agent.process(STREAM_TRADE_PERFORMANCE, f"redis-id-{event[FieldName.TRACE_ID]}", event)
            
            # Verify reflection was triggered after 2 fills
            mock_reflection.assert_called_once()
            
            # Verify recent fills buffer contains correct data
            assert len(reflection_agent._recent_fills) == 2
            assert reflection_agent._recent_fills[0][FieldName.SYMBOL] == "TSLA"
            assert reflection_agent._recent_fills[1][FieldName.SYMBOL] == "AAPL"


@pytest.mark.asyncio
async def test_learning_agents_handle_missing_trace_id():
    """Test that learning agents handle events with missing trace IDs gracefully."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    
    with patch('api.services.agents.pipeline_agents.log_structured') as mock_log:
        grade_agent = GradeAgent(mock_bus, mock_dlq)
        
        # Event without trace ID
        event_no_trace = {
            FieldName.PNL: 5.0,
            "symbol": "TSLA",
            # Missing FieldName.TRACE_ID
        }
        
        await grade_agent.process(STREAM_TRADE_PERFORMANCE, "redis-id-123", event_no_trace)
        
        # Verify event was still processed and logged
        mock_log.assert_any_call("info", "grade_agent_received_event", 
                                stream=STREAM_TRADE_PERFORMANCE, 
                                redis_id="redis-id-123", 
                                trace_id=None)


@pytest.mark.asyncio
async def test_learning_agents_stream_subscription_validation():
    """Test that learning agents are subscribed to correct streams."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    mock_redis = AsyncMock()
    
    # Test GradeAgent streams
    grade_agent = GradeAgent(mock_bus, mock_dlq)
    assert STREAM_EXECUTIONS in grade_agent.streams
    assert STREAM_TRADE_PERFORMANCE in grade_agent.streams
    
    # Test ICUpdater streams
    ic_updater = ICUpdater(mock_bus, mock_dlq, mock_redis)
    assert STREAM_TRADE_PERFORMANCE in ic_updater.streams
    
    # Test ReflectionAgent streams
    reflection_agent = ReflectionAgent(mock_bus, mock_dlq)
    assert STREAM_TRADE_PERFORMANCE in reflection_agent.streams
    assert STREAM_AGENT_GRADES in reflection_agent.streams
    assert STREAM_FACTOR_IC_HISTORY in reflection_agent.streams
    
    # Test StrategyProposer streams
    strategy_proposer = StrategyProposer(mock_bus, mock_dlq)
    assert STREAM_REFLECTION_OUTPUTS in strategy_proposer.streams


@pytest.mark.asyncio
async def test_learning_agents_consumer_identifiers():
    """Test that learning agents have correct consumer identifiers."""
    
    mock_bus = AsyncMock()
    mock_dlq = AsyncMock()
    mock_redis = AsyncMock()
    
    # Test consumer identifiers
    grade_agent = GradeAgent(mock_bus, mock_dlq)
    assert grade_agent.consumer == "grade-agent"
    
    ic_updater = ICUpdater(mock_bus, mock_dlq, mock_redis)
    assert ic_updater.consumer == "ic-updater"
    
    reflection_agent = ReflectionAgent(mock_bus, mock_dlq)
    assert reflection_agent.consumer == "reflection-agent"
    
    strategy_proposer = StrategyProposer(mock_bus, mock_dlq)
    assert strategy_proposer.consumer == "strategy-proposer"
