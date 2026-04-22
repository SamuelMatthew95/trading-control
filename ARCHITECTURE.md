# Trading System Architecture

## Overview

Complete production-grade trading system with strict enforcement of data integrity, agent boundaries, and mathematical guarantees.

## System Components

### 1. Agent Infrastructure

#### Agent Types
- **Analyst Agent**: Only outputs bias + confidence, CANNOT trade
- **Risk Agent**: Can block signals, reduce confidence, CANNOT trade  
- **Executor Agent**: ONLY role allowed to emit BUY/SELL signals

#### Agent Contracts
- **Signal Schema**: Strict validation with Pydantic models
- **Required Fields**: signal_id, agent_id, symbol, action, price, confidence
- **Role Permissions**: Enforced at execution gate

#### Agent Communication Flow
```
Agent Output → Contract Validation → Execution Gate → Pipeline → DB → WebSocket
```

### 2. API Endpoints

#### Trade Validation (`/api/trades`)
- `POST /validate` - Trade creation validation
- `PUT /validate/{trade_id}` - Trade update validation
- `GET /validate/relationships/{trade_id}` - Relationship validation
- `GET /validate/consistency/{agent_id}` - Agent consistency validation
- `GET /health` - Service health

#### P&L Recomputation (`/api/pnl-recompute`)
- `GET /trade/{trade_id}` - Individual trade P&L
- `GET /portfolio/{agent_id}` - Portfolio P&L
- `GET /validate/consistency` - Consistency validation
- `GET /health` - Service health

#### Trade Lifecycle (`/api/trades/lifecycle`)
- `POST /enforce/sell-before-buy` - SELL validation
- `POST /enforce/buy-sequence` - BUY validation
- `GET /violations/{agent_id}` - Violation tracking
- `GET /health` - Service health

#### Reconciliation (`/api/reconciliation`)
- `GET /validate` - System consistency validation
- `GET /pnl-recompute` - Portfolio P&L recomputation
- `GET /health` - Service health

### 3. Core Services

#### Event Pipeline (`/api/services/event_pipeline_refactored.py`)
**6 Strict Phases:**
1. **Ingestion** - Validate and normalize signals
2. **Idempotency Gate** - Check processed signals, ACK early if duplicate
3. **Trade Execution** - Pure logic to open/close trades and compute P&L
4. **Persistence** - Atomic DB writes with no duplicates
5. **Broadcast** - Emit WebSocket event only after DB success
6. **Acknowledgement** - ACK Redis stream only after all success

#### Trade Engine (`/api/services/trade_engine.py`)
- Core BUY/SELL logic with P&L calculation
- Trade lifecycle management
- Async SQLAlchemy session handling

#### Concurrent Trade Processor (`/api/services/concurrent_trade_processor.py`)
- Row-level locking with `FOR UPDATE SKIP LOCKED`
- Serialized per-symbol processing
- Prevents race conditions on concurrent SELL signals

#### Event Outbox (`/api/services/event_outbox.py`)
- Decouples DB commits from WebSocket broadcasts
- Guaranteed event delivery with retry mechanism
- Prevents UI lying when WebSocket fails

#### Reconciliation Service (`/api/services/reconciliation_service.py`)
- Ledger consistency checks
- P&L recomputation from source of truth
- System-wide consistency validation

#### P&L Recomputer (`/api/services/pnl_recomputation.py`)
- **Deterministic Formula**: `(exit_price - entry_price) × quantity`
- Never trusts stored P&L as truth
- Mathematical guarantees for consistency

#### Trade Lifecycle Enforcer (`/api/services/trade_lifecycle_enforcer.py`)
- **SELL before BUY Prevention** - Every SELL must have BUY parent
- Position consistency validation
- Orphaned trade detection

#### Schema Validation (`/api/services/schema_validation.py`)
- Strict signal schema enforcement
- Agent output validation
- Permission checking

#### Trade Validation (`/api/services/trade_validation.py`)
- **Required Identifiers**:
  - `signal_id` - Signal identifier for idempotency
  - `agent_id` - Agent identifier
  - `execution_id` - Execution identifier
  - `db_trade_id` - Database trade identifier
  - `websocket_event_id` - WebSocket event identifier

### 4. Agent Services

#### Agent Contracts (`/api/agents/contracts.py`)
- Strict `AgentOutput` schema with Pydantic validation
- Role-based permissions (Analyst/Risk/Executor)
- Confidence range enforcement (0-100)

#### Execution Gate (`/api/agents/execution_gate.py`)
- Validates ALL agent outputs before execution
- Role-based permission checking
- Automatic blocking/modification of invalid signals
- Risk level assessment

#### DB Memory (`/api/agents/db_memory.py`)
- Agents NEVER rely on memory or context
- Always query DB for current state
- Prevents hallucinations of positions/trades

#### Agent Idempotency (`/api/agents/agent_idempotency.py`)
- Double-layer protection (agent + pipeline)
- Memory-efficient tracking with automatic cleanup
- Prevents duplicate signal emission

#### Confidence Normalization (`/api/agents/confidence_normalization.py`)
- Derives confidence from measurable performance data
- Normalizes across agents (0-1 scale)
- Penalizes arbitrary confidence scores

#### System Consistency Checker (`/api/agents/system_consistency_checker.py`)
- Detects duplicate trades, missing closes, balance anomalies
- Validates position mismatches and volume patterns
- Global anomaly detection across all agents

### 5. Data Models

#### Canonical Events (`/api/core/events.py`)
- **SignalEvent**: Signal creation with metadata
- **TradeExecutionEvent**: Trade execution with P&L
- **PositionState**: Position tracking

#### Trade Ledger (`/api/core/models/trade_ledger.py`)
- **Constraints**: UNIQUE signal_id, single OPEN position per symbol/agent
- **Indexes**: Performance optimization
- **Relationships**: Parent/child trade linking

#### Trade Validation (`/api/core/trade_validation.py`)
- RequiredTradeFields: All required identifiers
- TradeRelationshipValidator: Parent/child validation
- WebSocketEventValidator: Event consistency

### 6. Database Constraints

#### Enforcement Rules
- **UNIQUE signal_id**: Prevents duplicate trades
- **Single OPEN position**: One open position per symbol/agent
- **Valid lifecycle**: BUY→OPEN, SELL→CLOSED
- **Parent/child integrity**: No orphaned trades

### 7. WebSocket & Broadcasting

#### Event Broadcasting
- **Outbox Pattern**: Reliable delivery with retry
- **Event Matching**: WebSocket events match DB state
- **Error Handling**: Graceful failure with retry

## Data Flow Architecture

### Signal Processing Flow
```
Agent Signal
    ↓
Contract Validation (Pydantic)
    ↓
Execution Gate (Role/Permission Check)
    ↓
Event Pipeline (6 Phases)
    ↓
Trade Engine (BUY/SELL Logic)
    ↓
DB Persistence (Constraints + Row Locking)
    ↓
Event Outbox (Reliable Delivery)
    ↓
WebSocket Broadcast
    ↓
Acknowledgment (Redis Stream)
```

### Trade Lifecycle Flow
```
BUY Signal → Open Position → DB Store → WebSocket Broadcast → ACK
SELL Signal → Validate Parent → Close Position → P&L Calculation → DB Store → WebSocket Broadcast → ACK
```

### Agent Communication Flow
```
Analyst Agent → Market Analysis → Bias/Confidence
    ↓
Risk Agent → Risk Assessment → Block/Modify
    ↓
Executor Agent → Final Decision → BUY/SELL Signal
    ↓
Execution Gate → Validation → Pipeline Processing
```

## Enforcement Guarantees

### 1. Data Integrity
- ✅ No duplicate trades (UNIQUE signal_id)
- ✅ No invalid trade sequences (SELL before BUY)
- ✅ No conflicting positions (single OPEN per symbol)
- ✅ No orphaned trades (parent/child validation)

### 2. Agent Boundaries
- ✅ No role violations (Analyst/Risk/Executor separation)
- ✅ No contradictory decisions (deterministic flow)
- ✅ No hallucinated positions (DB-only memory)
- ✅ No duplicate signals (agent-level idempotency)

### 3. Mathematical Guarantees
- ✅ Deterministic P&L calculation (entry→exit price)
- ✅ No arbitrary confidence (normalization system)
- ✅ No inconsistent state (global consistency checker)
- ✅ No calculation errors (recomputation validation)

### 4. System Reliability
- ✅ No silent failures (comprehensive error handling)
- ✅ No data loss (outbox pattern)
- ✅ No race conditions (row locking)
- ✅ No UI lying (event matching)

## Production Readiness

### Monitoring & Health Checks
- All services have `/health` endpoints
- Comprehensive logging with structured format
- Error tracking and alerting
- Performance metrics collection

### Testing & Validation
- Clean test system (no prints/main functions)
- Comprehensive endpoint testing
- Integration testing
- Load testing capabilities

### Security & Compliance
- Role-based access control
- Input validation and sanitization
- Audit trail for all trades
- Rate limiting and permission enforcement

## Complete System Status

**All components implemented and tested:**
- ✅ Event Pipeline with 6 strict phases
- ✅ Agent contracts and role separation
- ✅ Execution gating layer
- ✅ DB constraints and concurrency safety
- ✅ System consistency validation
- ✅ Confidence normalization
- ✅ Global anomaly detection
- ✅ Deterministic P&L recomputation
- ✅ Trade lifecycle enforcement
- ✅ Required identifier validation
- ✅ Clean test system

**Ready for production deployment with full guarantees for data integrity, agent boundaries, and mathematical accuracy.**
