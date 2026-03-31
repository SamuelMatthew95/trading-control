# Logging Standards & Trace ID Management

## Structured Logging Requirements

### Mandatory Logging Function
```python
# ONLY use log_structured from api.observability
from api.observability import log_structured

# Correct patterns
log_structured("info", "operation completed", 
              agent="ReasoningAgent", 
              symbol="BTC/USD",
              trace_id=trace_id)

log_structured("error", "operation failed", 
              agent="ExecutionEngine",
              exc_info=True)  # CRITICAL for errors
```

### Logging Anti-Patterns (NEVER USE)
```python
# ❌ WRONG - Old logging
logger.info("message")
logger.error("error", exc_info=exc)

# ❌ WRONG - Stringified exceptions (CI/CD failure)
log_structured("error", "failed", error=str(exc))

# ❌ WRONG - Print statements
print("debug info")
```

## Trace ID Lifecycle Management

### Trace ID Generation Rules
```python
# Use uuid4() only for NEW operations
new_trace_id = str(uuid.uuid4())

# NEVER generate new trace_id when processing existing events
# ALWAYS extract and propagate existing trace_id
incoming_trace_id = event_data.get("trace_id")
```

### Trace ID Propagation Pattern
```python
async def process_stream_event(self, event_data: dict) -> None:
    # 1. Extract trace_id from incoming event
    incoming_trace_id = event_data.get("trace_id")
    
    # 2. Generate processing trace_id if needed
    processing_trace_id = str(uuid.uuid4())
    
    # 3. Log the trace relationship
    log_structured("info", "trace propagation", 
                  agent=self.agent_id,
                  incoming_trace_id=incoming_trace_id,
                  processing_trace_id=processing_trace_id)
    
    # 4. Use processing_trace_id for this operation
    result = await self._do_work(event_data, processing_trace_id)
    
    # 5. Publish with processing_trace_id
    await self.redis.publish("output_stream", {
        "data": result,
        "trace_id": processing_trace_id,
        "source_agent": self.agent_id
    })
```

## Database Trace ID Integration

### SafeWriter Trace ID Requirements
```python
# All database writes must include trace_id
await writer.write(
    table="agent_runs",
    data={
        "strategy_id": strategy_id,
        "symbol": "BTC/USD",
        "action": "buy",
        "trace_id": processing_trace_id,  # MANDATORY
        "schema_version": "v3",
        "source": self.agent_id
    }
)
```

### Query Pattern for Trace Reconstruction
```python
# Reconstruct full operation from trace_id
async def get_operation_trace(trace_id: str) -> dict:
    async with get_async_session() as session:
        # Get agent runs
        agent_runs = await session.execute(
            select(AgentRun).where(AgentRun.trace_id == trace_id)
        )
        
        # Get agent logs
        agent_logs = await session.execute(
            select(AgentLog).where(AgentLog.trace_id == trace_id)
        )
        
        # Get vector memory entries
        vector_entries = await session.execute(
            select(VectorMemory).where(VectorMemory.metadata_["trace_id"].as_string() == trace_id)
        )
        
        return {
            "agent_runs": [run.__dict__ for run in agent_runs.scalars().all()],
            "agent_logs": [log.__dict__ for log in agent_logs.scalars().all()],
            "vector_memory": [vec.__dict__ for vec in vector_entries.scalars().all()]
        }
```

## Log Level Standards

### Log Level Usage
```python
# INFO: Normal operation flow
log_structured("info", "agent started", agent=self.agent_id)

# WARNING: Recoverable issues
log_structured("warning", "retry attempt", 
              attempt=3, 
              max_attempts=5,
              trace_id=trace_id)

# ERROR: Failures requiring attention
log_structured("error", "api call failed", 
              service="alpaca",
              exc_info=True)  # ALWAYS use exc_info=True
```

### Structured Data Requirements
```python
# Include relevant context in all logs
log_structured("info", "order processed", 
              order_id=order_id,
              symbol="BTC/USD",
              side="buy",
              quantity=0.1,
              execution_time_ms=1250,
              trace_id=trace_id)

# Use snake_case for all keys
# Include units in key names when applicable (time_ms, price_usd, qty_btc)
```

## Performance Monitoring

### Agent Performance Logging
```python
# Log agent processing times
start_time = time.time()
try:
    result = await process_event(event_data)
    processing_time_ms = (time.time() - start_time) * 1000
    
    log_structured("info", "agent processing completed", 
                  agent=self.agent_id,
                  processing_time_ms=processing_time_ms,
                  trace_id=trace_id)
                  
except Exception as exc:
    processing_time_ms = (time.time() - start_time) * 1000
    
    log_structured("error", "agent processing failed", 
                  agent=self.agent_id,
                  processing_time_ms=processing_time_ms,
                  exc_info=True)
```

### Redis Stream Lag Monitoring
```python
# Monitor consumer lag
async def check_stream_lag(self):
    for stream in self.input_streams:
        groups = await redis.xinfo_groups(stream)
        for group in groups:
            lag = group.get("lag", 0)
            if lag > self.max_lag_threshold:
                log_structured("warning", "stream lag detected", 
                              stream=stream,
                              consumer_group=group["name"],
                              lag=lag,
                              trace_id=trace_id)
