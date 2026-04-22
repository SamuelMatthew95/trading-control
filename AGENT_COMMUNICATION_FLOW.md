# Agent Communication Flow - Step by Step

## Complete Walkthrough: How Agents Talk to Generate BUY/SELL Signals

### Phase 1: Analyst Agent - Market Analysis

**Step 1: Analyst Receives Market Data**
```
Input: Market data (price, volume, indicators)
Agent: Analyst Agent
```

**Step 2: Analyst Processes Market Data**
```python
# Analyst Agent Logic (simplified)
async def analyze_market(symbol, market_data):
    # Technical analysis
    rsi = calculate_rsi(market_data)
    sma = calculate_sma(market_data)
    volume_trend = analyze_volume(market_data)
    
    # Generate bias and confidence
    if rsi < 30 and volume_trend == "increasing":
        bias = "BULLISH"
        confidence = 75
    elif rsi > 70 and volume_trend == "decreasing":
        bias = "BEARISH"
        confidence = 80
    else:
        bias = "NEUTRAL"
        confidence = 50
    
    return {
        "signal_id": generate_signal_id(),
        "agent_id": "analyst_001",
        "role": "analyst",
        "symbol": symbol,
        "action": "ANALYZE",  # Analyst cannot trade
        "bias": bias,
        "confidence": confidence,
        "reason": f"RSI: {rsi}, Volume: {volume_trend}",
        "timestamp": datetime.utcnow(),
    }
```

**Step 3: Analyst Outputs Analysis (NOT TRADE)**
```json
{
    "signal_id": "analyst_123",
    "agent_id": "analyst_001", 
    "role": "analyst",
    "symbol": "BTC",
    "action": "ANALYZE",
    "bias": "BULLISH",
    "confidence": 75,
    "reason": "RSI: 25, Volume: increasing",
    "timestamp": "2026-04-13T16:20:00Z"
}
```

### Phase 2: Risk Agent - Risk Assessment

**Step 4: Risk Agent Receives Analysis**
```
Input: Analyst analysis
Agent: Risk Agent
```

**Step 5: Risk Agent Evaluates Risk**
```python
# Risk Agent Logic (simplified)
async def assess_risk(analyst_output):
    # Risk factors
    agent_performance = get_agent_performance(analyst_output["agent_id"])
    market_volatility = get_market_volatility(analyst_output["symbol"])
    position_exposure = get_current_exposure(analyst_output["symbol"])
    
    # Risk scoring
    risk_score = calculate_risk_score(
        agent_performance,
        market_volatility, 
        position_exposure
    )
    
    # Risk decision
    if risk_score > 80:
        decision = "BLOCK"
        adjusted_confidence = 0
    elif risk_score > 60:
        decision = "MODIFY"
        adjusted_confidence = analyst_output["confidence"] * 0.7
    else:
        decision = "APPROVE"
        adjusted_confidence = analyst_output["confidence"]
    
    return {
        "signal_id": analyst_output["signal_id"],
        "agent_id": "risk_001",
        "role": "risk",
        "symbol": analyst_output["symbol"],
        "action": "RISK_ASSESSMENT",  # Risk cannot trade
        "original_confidence": analyst_output["confidence"],
        "adjusted_confidence": adjusted_confidence,
        "decision": decision,
        "risk_score": risk_score,
        "reason": f"Risk score: {risk_score}, Decision: {decision}",
        "timestamp": datetime.utcnow(),
    }
```

**Step 6: Risk Agent Outputs Risk Assessment (NOT TRADE)**
```json
{
    "signal_id": "analyst_123",
    "agent_id": "risk_001",
    "role": "risk", 
    "symbol": "BTC",
    "action": "RISK_ASSESSMENT",
    "original_confidence": 75,
    "adjusted_confidence": 52.5,
    "decision": "MODIFY",
    "risk_score": 65,
    "reason": "Risk score: 65, Decision: MODIFY",
    "timestamp": "2026-04-13T16:21:00Z"
}
```

### Phase 3: Executor Agent - Final Trading Decision

**Step 7: Executor Agent Receives Both Inputs**
```
Input: Analyst analysis + Risk assessment
Agent: Executor Agent
```

**Step 8: Executor Agent Makes Final Decision**
```python
# Executor Agent Logic (simplified)
async def execute_decision(analyst_output, risk_assessment):
    # Combine inputs
    final_confidence = risk_assessment["adjusted_confidence"]
    risk_decision = risk_assessment["decision"]
    
    # Execution logic
    if risk_decision == "BLOCK":
        return {
            "signal_id": analyst_output["signal_id"],
            "agent_id": "executor_001",
            "role": "executor",
            "symbol": analyst_output["symbol"],
            "action": "HOLD",
            "confidence": 0,
            "reason": "Risk agent blocked execution",
            "timestamp": datetime.utcnow(),
        }
    
    # Determine trade action
    if analyst_output["bias"] == "BULLISH" and final_confidence > 50:
        action = "BUY"
    elif analyst_output["bias"] == "BEARISH" and final_confidence > 50:
        action = "SELL"
    else:
        action = "HOLD"
    
    # Get execution parameters
    current_price = get_market_price(analyst_output["symbol"])
    position_size = calculate_position_size(final_confidence, risk_assessment["risk_score"])
    
    return {
        "signal_id": analyst_output["signal_id"],
        "agent_id": "executor_001",
        "role": "executor",
        "symbol": analyst_output["symbol"],
        "action": action,
        "price": current_price,
        "quantity": position_size,
        "confidence": final_confidence,
        "reason": f"Final decision: {action} at {current_price}",
        "timestamp": datetime.utcnow(),
    }
```

**Step 9: Executor Agent Outputs Trading Signal (ONLY EXECUTOR CAN TRADE)**
```json
{
    "signal_id": "analyst_123",
    "agent_id": "executor_001",
    "role": "executor",
    "symbol": "BTC",
    "action": "BUY",
    "price": 50000,
    "quantity": 1.0,
    "confidence": 52.5,
    "reason": "Final decision: BUY at 50000",
    "timestamp": "2026-04-13T16:22:00Z"
}
```

### Phase 4: System Processing

**Step 10: Contract Validation**
```
Input: Executor signal
Service: Contract Validation
```
```python
# Contract Validation
async def validate_executor_signal(signal):
    # Validate required fields
    required_fields = ["signal_id", "agent_id", "symbol", "action", "price", "quantity"]
    for field in required_fields:
        if field not in signal:
            raise ValidationError(f"Missing required field: {field}")
    
    # Validate role permissions
    if signal["role"] != "executor":
        raise ValidationError(f"Only executor can emit trading signals")
    
    # Validate action
    if signal["action"] not in ["BUY", "SELL", "HOLD"]:
        raise ValidationError(f"Invalid action: {signal['action']}")
    
    return True
```

**Step 11: Execution Gate**
```
Input: Validated signal
Service: Execution Gate
```
```python
# Execution Gate
async def execution_gate(signal):
    # Check agent permissions
    agent_permissions = get_agent_permissions(signal["agent_id"])
    
    # Validate position limits
    current_positions = get_open_positions(signal["agent_id"], signal["symbol"])
    if signal["action"] == "BUY" and current_positions:
        return {"decision": "BLOCK", "reason": "Open position already exists"}
    
    # Validate SELL before BUY
    if signal["action"] == "SELL" and not current_positions:
        return {"decision": "BLOCK", "reason": "No open position to close"}
    
    return {"decision": "APPROVE", "reason": "Signal approved"}
}
```

**Step 12: Event Pipeline Processing**
```
Input: Approved signal
Service: Event Pipeline (6 phases)
```
```python
# Event Pipeline
async def process_signal(signal):
    # Phase 1: Ingestion
    normalized_signal = await ingest_signal(signal)
    
    # Phase 2: Idempotency Gate
    if await is_duplicate_signal(normalized_signal["signal_id"]):
        return await acknowledge_duplicate()
    
    # Phase 3: Trade Execution
    trade_result = await execute_trade(normalized_signal)
    
    # Phase 4: Persistence
    db_trade_id = await persist_to_database(trade_result)
    
    # Phase 5: Broadcast
    websocket_event_id = await broadcast_to_frontend(trade_result)
    
    # Phase 6: Acknowledgment
    await acknowledge_to_redis_stream(signal["signal_id"])
    
    return {
        "signal_id": signal["signal_id"],
        "db_trade_id": db_trade_id,
        "websocket_event_id": websocket_event_id,
        "status": "completed"
    }
```

### Phase 5: Database Storage & WebSocket Broadcast

**Step 13: Database Storage**
```sql
-- Trade Ledger Entry
INSERT INTO trade_ledger (
    trade_id,
    signal_id,
    agent_id,
    symbol,
    trade_type,
    quantity,
    entry_price,
    status,
    created_at
) VALUES (
    'db_trade_456',
    'analyst_123',
    'executor_001',
    'BTC',
    'BUY',
    1.0,
    50000,
    'OPEN',
    '2026-04-13T16:22:00Z'
);
```

**Step 14: WebSocket Broadcast**
```json
{
    "type": "trade_execution",
    "event_id": "ws_event_789",
    "payload": {
        "signal_id": "analyst_123",
        "agent_id": "executor_001",
        "symbol": "BTC",
        "action": "BUY",
        "price": 50000,
        "quantity": 1.0,
        "status": "OPEN",
        "db_trade_id": "db_trade_456"
    },
    "timestamp": "2026-04-13T16:22:01Z"
}
```

### Phase 6: SELL Signal Flow (Same Pattern)

**Step 15: Later SELL Signal**
```
Analyst: Detects bearish signals
Risk: Assesses risk (might block or modify)
Executor: Makes final SELL decision
System: Validates SELL has BUY parent
Database: Links SELL to existing BUY
WebSocket: Broadcasts position close
```

### Complete Communication Flow Summary

```
1. Analyst Agent → Market Analysis → Bias/Confidence
2. Risk Agent → Risk Assessment → Block/Modify/Approve
3. Executor Agent → Final Decision → BUY/SELL Signal
4. Contract Validation → Schema Check → Required Fields
5. Execution Gate → Permission Check → Position Validation
6. Event Pipeline → 6 Phase Processing → Trade Execution
7. Database → Atomic Storage → Constraints Enforcement
8. WebSocket → Event Broadcast → UI Update
9. Acknowledgment → Redis Stream → Signal Completion
```

### Key Communication Points

1. **Agent-to-Agent**: Analyst → Risk → Executor (linear chain)
2. **Agent-to-System**: Executor → Contract Validation → Execution Gate
3. **System-to-Database**: Pipeline → Atomic Storage with Constraints
4. **System-to-Client**: WebSocket Broadcast → Real-time Updates
5. **System-to-Source**: Redis Stream Acknowledgment → Signal Completion

### Enforcement Points

1. **Role Separation**: Only Executor can emit trading signals
2. **Decision Flow**: Analyst → Risk → Executor (no skipping)
3. **Permission Check**: Risk can block, Executor cannot override
4. **Database Constraints**: No duplicates, proper lifecycle
5. **Event Matching**: WebSocket events match DB state

This ensures no agent can bypass the chain, no contradictory decisions, and all trades are properly validated and tracked.
