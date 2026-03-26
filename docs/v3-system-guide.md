# V3 Event-Driven Agent System

## Overview

The V3 system implements a fully event-driven architecture with 9 autonomous agents communicating exclusively via Redis Streams, with atomic Postgres writes through SafeWriter v3.

## Architecture

### Core Components

1. **SafeWriter v3** - Atomic, idempotent database writes with deduplication
2. **Redis Streams** - Event-driven communication between agents
3. **Event Bus** - High-performance stream management
4. **DLQ Manager** - Dead letter queue for failed events
5. **9 Autonomous Agents** - Specialized processing units

### Agent Pipeline

```
market_ticks → SignalGenerator → signals → ReasoningAgent → orders → 
ExecutionAgent → executions → trade_performance → 
├── GradeAgent → agent_grades
├── ICUpdaterAgent → ic_weights  
├── ReflectionAgent → reflections → StrategyProposerAgent → proposals
├── HistoryAgent → historical_insights
└── NotificationAgent → notifications
```

## Key Features

### ✅ V3 Schema Enforcement
- **Strict validation** - Only v3 events accepted
- **Auto-DLQ** - v2 events automatically moved to DLQ
- **Traceability** - Every event has `msg_id` + `trace_id`
- **Source tracking** - Required source field for audit

### ✅ Atomic Processing
- **SafeWriter transactions** - All-or-nothing writes
- **Idempotent operations** - Safe retries without duplicates
- **Claim-first pattern** - Exactly-once processing guarantee

### ✅ Event-Driven Design
- **No sleeps** - Pure event-driven consumption
- **Redis Streams** - High-performance messaging
- **Backpressure handling** - Exponential backoff on errors
- **Graceful shutdown** - Clean agent lifecycle management

### ✅ Full Observability
- **Structured logging** - Every operation logged with context
- **End-to-end tracing** - Follow `trace_id` through pipeline
- **Performance metrics** - Agent timing and throughput
- **Error tracking** - Comprehensive error handling

## Quick Start

### 1. Database Migration

```bash
# Apply v3 schema migration
cd api
alembic upgrade head

# Or apply specific v3 migration
alembic upgrade upgrade_to_v3
```

### 2. Start the System

```bash
# Start the complete v3 system
cd api
python v3_system_startup.py
```

### 3. Send Test Events

```python
import asyncio
from redis.asyncio import Redis

async def send_test_event():
    redis = Redis()
    await redis.xadd("market_ticks", {
        "schema_version": "v3",
        "msg_id": "test-001",
        "trace_id": "trace-001", 
        "symbol": "AAPL",
        "price": 150.25,
        "source": "manual_test"
    })
    await redis.close()

asyncio.run(send_test_event())
```

## Agent Details

### 1. SignalGeneratorAgent
- **Input**: `market_ticks` stream
- **Output**: `signals` stream
- **Function**: Generate trading signals from market data
- **Writes**: VectorMemory (for signal history)

### 2. ReasoningAgent  
- **Input**: `signals` stream
- **Output**: `orders` stream
- **Function**: Process signals and create orders
- **Writes**: Orders, AgentRun records

### 3. ExecutionAgent
- **Input**: `orders` stream  
- **Output**: `executions` stream
- **Function**: Execute orders and track fills
- **Writes**: Executions, Positions

### 4. GradeAgent
- **Input**: `trade_performance` stream
- **Output**: `agent_grades` stream
- **Function**: Grade agent performance
- **Writes**: AgentGrades

### 5. ICUpdaterAgent
- **Input**: `trade_performance` stream
- **Output**: `ic_weights` stream  
- **Function**: Update Information Coefficient weights
- **Writes**: Events (IC weight updates)

### 6. ReflectionAgent
- **Input**: `trade_performance` stream
- **Output**: `reflections` stream
- **Function**: Generate performance insights
- **Writes**: VectorMemory (reflections)

### 7. StrategyProposerAgent
- **Input**: `reflections` stream
- **Output**: `proposals` stream
- **Function**: Propose strategy improvements
- **Writes**: Events (strategy proposals)

### 8. HistoryAgent
- **Input**: `trade_performance` stream
- **Output**: `historical_insights` stream
- **Function**: Analyze historical patterns
- **Writes**: VectorMemory (historical insights)

### 9. NotificationAgent
- **Input**: All streams (*)
- **Output**: `notifications` stream
- **Function**: Send notifications for important events
- **Writes**: Events (notifications)

## Schema Requirements

### V3 Event Schema

All events must include:

```json
{
  "schema_version": "v3",
  "msg_id": "uuid-string",
  "trace_id": "uuid-string", 
  "source": "agent-name",
  "timestamp": "iso-datetime",
  "...": "event-specific-fields"
}
```

### Required Fields by Model

- **Orders**: `strategy_id`, `symbol`, `side`, `order_type`, `quantity`, `idempotency_key`
- **AgentLogs**: `agent_id`, `level`, `message`
- **AgentGrades**: `agent_id`, `agent_run_id`, `grade_type`, `score`
- **TradePerformance**: `strategy_id`, `symbol`, `trade_id`, `entry_price`, `quantity`
- **VectorMemory**: `content`, `content_type`, `embedding`

## Monitoring

### System Health

```bash
# Check Redis streams
redis-cli XINFO STREAMS market_ticks signals orders

# Check agent status
redis-cli XINFO GROUPS market_ticks

# Check DLQ
redis-cli XINFO STREAMS dlq:market_ticks dlq:signals
```

### Database Queries

```sql
-- Check processed events
SELECT stream, COUNT(*) FROM processed_events GROUP BY stream;

-- Trace an event flow
SELECT * FROM agent_logs WHERE trace_id = 'your-trace-id';

-- Check agent performance  
SELECT agent_id, AVG(score) as avg_score FROM agent_grades 
WHERE grade_type = 'overall' GROUP BY agent_id;
```

## Testing

### Run Integration Tests

```bash
# Run full system test
cd tests
python test_v3_system.py

# Run with pytest
pytest tests/test_v3_system.py -v
```

### Test Scenarios

1. **Schema Validation** - v3 accepted, v2 sent to DLQ
2. **Traceability** - End-to-end `trace_id` flow
3. **Atomicity** - SafeWriter transaction behavior
4. **Error Handling** - Retry and DLQ mechanisms
5. **Concurrency** - Parallel message processing
6. **Observability** - Structured logging verification

## Troubleshooting

### Common Issues

#### Events Not Processing
```bash
# Check if agents are running
redis-cli XINFO GROUPS stream_name

# Check consumer lag
redis-cli XINFO CONSUMERS stream_name group_name
```

#### V2 Events in DLQ
```bash
# Check DLQ contents
redis-cli XRANGE dlq:stream_name - +

# Process DLQ manually
redis-cli XREADGROUP GROUP dlq_group consumer_name COUNT 1 STREAMS dlq:stream_name >
```

#### Database Write Errors
```sql
-- Check constraint violations
SELECT * FROM pg_stat_activity WHERE state = 'idle in transaction';

-- Check processed events for duplicates
SELECT msg_id, COUNT(*) FROM processed_events GROUP BY msg_id HAVING COUNT(*) > 1;
```

### Performance Tuning

#### Redis Optimization
```bash
# Set appropriate memory limits
redis-cli CONFIG SET maxmemory 2gb
redis-cli CONFIG SET maxmemory-policy allkeys-lru

# Monitor Redis performance
redis-cli INFO memory
redis-cli INFO stats
```

#### Database Optimization
```sql
-- Add indexes for traceability
CREATE INDEX CONCURRENTLY idx_agent_runs_trace_v3 ON agent_runs(trace_id);
CREATE INDEX CONCURRENTLY idx_events_trace_id ON events(data->>'trace_id');

-- Analyze query performance
EXPLAIN ANALYZE SELECT * FROM agent_logs WHERE trace_id = 'test';
```

## Configuration

### Environment Variables

```bash
# Redis configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Database configuration  
DATABASE_URL=postgresql://user:pass@localhost/trading_control

# System configuration
LOG_LEVEL=INFO
MAX_AGENTS=9
STREAM_BLOCK_MS=100
DLQ_MAX_RETRIES=3
```

### Agent Configuration

```python
# Custom agent behavior can be configured via environment
SIGNAL_GENERATOR_CONFIDENCE_THRESHOLD=0.8
GRADE_AGENT_PASSING_SCORE=6.0
NOTIFICATION_AGENT_ALERT_THRESHOLD=1000.0
```

## Deployment

### Production Deployment

1. **Database Migration**
   ```bash
   alembic upgrade head
   ```

2. **Redis Setup**
   ```bash
   # Configure Redis with persistence
   redis-cli CONFIG SET save "900 1 300 10 60 10000"
   ```

3. **Start Services**
   ```bash
   # Start v3 system
   python v3_system_startup.py
   
   # Start API server (separate process)
   python main.py
   ```

4. **Health Checks**
   ```bash
   # Verify all streams created
   redis-cli XINFO STREAMS market_ticks signals orders executions trade_performance agent_grades ic_weights reflections proposals historical_insights notifications
   ```

### Monitoring Setup

- **Prometheus**: Export Redis and database metrics
- **Grafana**: Dashboard for system health
- **Alertmanager**: Alerts for high DLQ volume or agent failures

## Development

### Adding New Agents

1. **Create Agent Class**
   ```python
   class NewAgent(V3AgentConsumer):
       def __init__(self, bus, dlq, redis):
           super().__init__(bus, dlq, redis, "input_stream", "new-agent", SafeWriter(AsyncSessionFactory))
       
       async def process(self, data):
           # Process data
           await self.publish_event("output_stream", result_data)
   ```

2. **Register Agent**
   ```python
   V3_AGENTS.append(NewAgent)
   ```

3. **Add Tests**
   ```python
   async def test_new_agent(self, event_bus, redis_client):
       # Test agent behavior
   ```

### Schema Evolution

When updating schema:

1. **Create new migration**
   ```bash
   alembic revision --autogenerate -m "v4 schema updates"
   ```

2. **Update SafeWriter validation**
   ```python
   def _validate_schema_v4(self, data, model_name):
       # New validation logic
   ```

3. **Update consumer filtering**
   ```python
   if schema_version not in ["v3", "v4"]:
       # Send to DLQ
   ```

## Dashboard Integration

The v3 system integrates with the existing dashboard at:
`https://trading-control-khaki.vercel.app/dashboard/system`

### Available Metrics

- **Agent Status**: Running/stopped agents
- **Stream Health**: Message rates and consumer lag  
- **Error Rates**: DLQ volume and processing errors
- **Performance**: Agent timing and throughput
- **Traceability**: End-to-end request tracing

### Real-time Updates

Dashboard updates are pushed via WebSocket from the NotificationAgent, ensuring real-time visibility into system performance.

---

## Support

For issues or questions:
1. Check system logs: `grep "v3_system" /var/log/trading_control/*.log`
2. Verify database connectivity: `psql $DATABASE_URL -c "SELECT 1"`
3. Check Redis connectivity: `redis-cli ping`
4. Review DLQ for processing errors

The v3 system provides a robust, scalable foundation for autonomous trading operations with full observability and reliability guarantees.
