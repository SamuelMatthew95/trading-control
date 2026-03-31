# Agent Hand-off Protocols & Communication

## Agent Communication Rules

### Redis Stream Architecture
```python
# Stream naming convention
stream_name = "{source}_{target}"  # e.g., "signals_reasoning"
consumer_group = "{target}_agents"   # e.g., "reasoning_agents"

# Standard event envelope
event = {
    "type": "signal_data|decision|execution|grade",
    "data": {...},
    "trace_id": "uuid-string",
    "timestamp": "ISO-8601",
    "source_agent": "SignalGenerator|ReasoningAgent|..."
}
```

### Trace ID Propagation (MANDATORY)
```python
# ALL agents must follow this pattern
async def process_event(self, event_data: dict) -> None:
    # 1. Extract incoming trace_id
    incoming_trace_id = event_data.get("trace_id")
    
    # 2. Generate new trace_id for this processing
    current_trace_id = str(uuid.uuid4())
    
    # 3. Log the handoff
    log_structured("info", "agent handoff", 
                  agent=self.agent_id,
                  incoming_trace_id=incoming_trace_id,
                  current_trace_id=current_trace_id)
    
    # 4. Process with current_trace_id
    result = await self._do_work(event_data, current_trace_id)
    
    # 5. Publish with current_trace_id
    await self.redis.publish("output_stream", {
        "type": "agent_result",
        "data": result,
        "trace_id": current_trace_id,
        "agent_id": self.agent_id
    })
```

## Specific Hand-off Patterns

### SignalGenerator → ReasoningAgent
```python
# SignalGenerator output (signals stream)
signal_event = {
    "type": "trading_signal",
    "data": {
        "symbol": "BTC/USD",
        "signal_type": "momentum_buy",
        "confidence": 0.85,
        "indicators": {
            "rsi": 35.2,
            "macd_cross": True,
            "volume_spike": 1.5
        }
    },
    "trace_id": trace_id
}
```

### ReasoningAgent → ExecutionEngine
```python
# ReasoningAgent output (decisions stream)
decision_event = {
    "type": "trading_decision",
    "data": {
        "symbol": "BTC/USD",
        "action": "buy",
        "quantity": 0.1,
        "order_type": "market",
        "reasoning": "Momentum signal with RSI oversold",
        "confidence": 0.82,
        "risk_metrics": {
            "atr_stop": 42000,
            "position_size_pct": 0.05,
            "rr_ratio": 2.0
        }
    },
    "trace_id": trace_id
}
```

### ExecutionEngine → GradeAgent
```python
# ExecutionEngine output (executions stream)
execution_event = {
    "type": "trade_execution",
    "data": {
        "order_id": "uuid",
        "symbol": "BTC/USD",
        "side": "buy",
        "quantity": 0.1,
        "fill_price": 43250.75,
        "execution_time_ms": 1200,
        "broker_fees": 0.43,
        "slippage_bps": 2.1
    },
    "trace_id": trace_id
}
```

## Agent State Synchronization

### AgentStateRegistry Integration
```python
# Every agent must register and update state
from api.services.agent_state import AgentStateRegistry

class YourAgent:
    def __init__(self, redis_client):
        self.redis = redis_client
        self.agent_id = "YourAgent"
        self.state_registry = AgentStateRegistry(redis_client)
        
    async def process_event(self, event_data: dict) -> None:
        # Record event start
        await self.state_registry.record_event(self.agent_id)
        
        # ... process event ...
        
        # Update heartbeat
        await self.state_registry.update_heartbeat(self.agent_id)
```

### Consumer Group Management
```python
# Standard consumer group setup
async def setup_consumer_groups():
    groups = {
        "signals": ["reasoning_agents"],
        "decisions": ["execution_agents"], 
        "executions": ["grading_agents"],
        "grades": ["learning_agents"]
    }
    
    for stream, consumer_groups in groups.items():
        for group in consumer_groups:
            # Use positional arguments (CRITICAL for tests)
            await redis.xgroup_create(stream, group, "$", mkstream=True)
```

## Error Recovery Patterns

### Dead Letter Queue Handling
```python
# Failed events go to DLQ after retries
async def handle_processing_error(event_data: dict, error: Exception):
    await redis.xadd("dlq_events", {
        "failed_event": json.dumps(event_data),
        "error": str(error),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "retry_count": event_data.get("retry_count", 0)
    })
```

### Circuit Breaker per Agent
```python
class AgentCircuitBreaker:
    def __init__(self, failure_threshold: int = 5):
        self.failure_threshold = failure_threshold
        self.failure_count = 0
        self.last_failure_time = None
        
    async def call(self, func, *args, **kwargs):
        if self.is_open():
            log_structured("warning", "circuit breaker open", 
                          agent=self.agent_id)
            return None
            
        try:
            result = await func(*args, **kwargs)
            self.reset()
            return result
        except Exception as exc:
            self.record_failure()
            log_structured("error", "agent circuit breaker triggered", 
                          agent=self.agent_id,
                          exc_info=True)
            raise
