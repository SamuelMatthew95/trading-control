# Storage Architecture — Single Source of Truth
# Memory File: Storage
# Version: v1.0
# Last Updated: 2026-04-14

## The Four Storage Layers

Every piece of data in the system belongs to exactly one primary layer.
No data should live in two layers unless the second is an explicit **fallback or audit copy**.

```
┌─────────────────────────────────────────────────────────────────┐
│  Redis Streams     — agent-to-agent event bus (append-only)     │
│  Redis KV          — shared mutable state (fast, ephemeral)     │
│  Postgres          — durable record of truth (persistent)       │
│  InMemoryStore     — Postgres substitute when DB is down only   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Redis Streams — Event Bus (Agent Communication)

**Use for:** Messages flowing between agents. One producer → consumer group(s).

**Rule:** Streams carry EVENTS, not state. If you need to query "what is the
current price", use Redis KV, not a stream.

```python
# Correct: publish an event
await bus.publish(STREAM_DECISIONS, {"action": "buy", ...})

# WRONG: store current state as a stream message and re-read it
```

**All stream constants live in `api/constants.py` prefixed `STREAM_`.**

| Stream | Producer | Consumers |
|--------|---------|-----------|
| `market_ticks` | PricePoller | SignalGenerator |
| `market_events` | PricePoller | Dashboard/WS |
| `signals` | SignalGenerator | ReasoningAgent |
| `decisions` | ReasoningAgent, RiskGuardian | ExecutionEngine |
| `executions` | ExecutionEngine | GradeAgent, ICUpdater, NotificationAgent |
| `trade_performance` | ExecutionEngine | GradeAgent, ICUpdater, ReflectionAgent |
| `risk_alerts` | RiskGuardian, AgentSupervisor | NotificationAgent |
| `agent_logs` | All agents | NotificationAgent |
| `agent_grades` | GradeAgent | Dashboard |
| `reflection_outputs` | ReflectionAgent | StrategyProposer |
| `proposals` | StrategyProposer | NotificationAgent |
| `factor_ic_history` | ICUpdater | ReflectionAgent |
| `notifications` | NotificationAgent | Dashboard/WS |
| `dlq` | DLQManager | DLQManager (retry) |

---

## Redis KV — Shared Mutable State

**Use for:** State that must be visible across multiple processes in real-time
with sub-millisecond read latency. NOT for persistent records.

**Rule:** Every Redis KV key must be declared as a constant in `api/constants.py`.
Never write raw string keys. Every key must have a documented owner and TTL policy.

### Category 1 — Market Data Cache
Short-lived price snapshots. Written by PricePoller, read by any service needing
current prices. Expires automatically so stale prices are never used.

| Constant | Key Pattern | TTL | Owner |
|----------|------------|-----|-------|
| `REDIS_KEY_PRICES` | `prices:{symbol}` | 30s | PricePoller |

**Fallback if absent:** Return `None`; callers skip the operation gracefully.

```python
# Pattern
pipe.set(REDIS_KEY_PRICES.format(symbol=symbol), payload, ex=REDIS_PRICES_TTL_SECONDS)
price_raw = await redis.get(REDIS_KEY_PRICES.format(symbol="BTC/USD"))
```

### Category 2 — Computed Configuration
Factor weights recomputed by ICUpdater after every batch of trades. Long TTL
survives overnight so ReasoningAgent always has weights even if no trades ran.

| Constant | Key Pattern | TTL | Owner |
|----------|------------|-----|-------|
| `REDIS_KEY_IC_WEIGHTS` | `alpha:ic_weights` | 25h | ICUpdater |

**Fallback if absent:** Proceed with empty weights (no crash; degraded reasoning).

```python
await redis.set(REDIS_KEY_IC_WEIGHTS, json.dumps(weights), ex=REDIS_IC_WEIGHTS_TTL_SECONDS)
```

### Category 3 — Control Plane (Circuit Breaker)
Safety-critical flags. These are the ONLY Redis keys where a missing value has
a defined meaning: absence = switch is OFF.

| Constant | Key Pattern | TTL | Owner |
|----------|------------|-----|-------|
| `REDIS_KEY_KILL_SWITCH` | `kill_switch:active` | None | RiskGuardian |
| `REDIS_KEY_KILL_SWITCH_UPDATED_AT` | `kill_switch:updated_at` | None | RiskGuardian |

**CRITICAL:** If Redis is unavailable during a kill switch check, the check
**raises an exception**, which routes the order to the DLQ. This is intentional
— failing closed is safer than failing open.

```python
# ExecutionEngine — first line of process()
if await self.redis.get(REDIS_KEY_KILL_SWITCH) == "1":
    raise RuntimeError("KillSwitchActive")
```

### Category 4 — Paper Broker State
Mutable simulation state for the paper trading engine. Redis is the
**primary store** for in-flight paper state. Postgres is a **durable mirror**
written after each fill (positions table).

| Constant | Key Pattern | TTL | Owner |
|----------|------------|-----|-------|
| `REDIS_KEY_PAPER_CASH` | `paper:cash` | None | PaperBroker |
| `REDIS_KEY_PAPER_POSITION` | `paper:positions:{symbol}` | None | PaperBroker |
| `REDIS_KEY_PAPER_ORDER` | `paper:order:{broker_order_id}` | None | PaperBroker |

**Fallback if absent:** Default to cash=100k, position=flat. Position truth
can be reconstructed from Postgres `positions` table.

### Category 5 — Coordination / Distributed Locking
Ephemeral mutexes. Written with `NX` (acquire-if-not-exists) and a short TTL
so locks self-expire if the holder crashes.

| Constant | Key Pattern | TTL | Owner |
|----------|------------|-----|-------|
| `REDIS_KEY_ORDER_LOCK` | `order_lock:{symbol}` | 5s | ExecutionEngine |

**Fallback if Redis down:** Lock acquisition raises exception → order rejected.
Correct: concurrent orders for the same symbol must not proceed.

### Category 6 — Agent Health / Heartbeats
Written by every agent after processing each event. Dashboard reads these to
show ACTIVE / STALE / OFFLINE status. TTL self-expires stale agents.

| Constant | Key Pattern | TTL | Owner |
|----------|------------|-----|-------|
| `REDIS_AGENT_STATUS_KEY` | `agent:status:{name}` | 5min | Each agent |

**Dual-write:** Always written to both Redis AND Postgres `agent_heartbeats`
table via `write_heartbeat()`. Never write directly to Redis for heartbeats.

```python
# ALWAYS use the shared module — never raw redis.set for heartbeats
from api.services.agent_heartbeat import write_heartbeat
await write_heartbeat(redis, AGENT_REASONING, last_event="processed BTC/USD")
```

**Fallback if absent:** Dashboard shows agent as OFFLINE.

### Category 7 — LLM Budget Tracking
Daily counters for token and cost usage. Reset implicitly by date change (key
includes ISO date). No explicit TTL — keys accumulate until replaced by next day.

| Constant | Key Pattern | TTL | Owner |
|----------|------------|-----|-------|
| `REDIS_KEY_LLM_TOKENS` | `llm:tokens:{date}` | None | ReasoningAgent |
| `REDIS_KEY_LLM_COST` | `llm:cost:{date}` | None | ReasoningAgent |

**Fallback if absent:** Treat as 0 (under budget). Consequence: budget may be
temporarily over-spent during Redis recovery. Acceptable risk.

### Category 8 — Infrastructure / Liveness
Worker heartbeats and DLQ metadata.

| Constant | Key Pattern | TTL | Owner |
|----------|------------|-----|-------|
| `REDIS_KEY_WORKER_HEARTBEAT` | `worker:heartbeat` | 120s | PricePoller |
| `REDIS_KEY_DLQ` | `dlq:{stream}` | 86400s (retries) | DLQManager |

---

## Postgres — Durable Records

**Use for:** Everything that must survive a Redis restart or system crash.
Postgres is the audit trail and the source of truth for all historical data.

| Table | Written by | InMemoryStore fallback? |
|-------|-----------|------------------------|
| `orders` | ExecutionEngine | Yes |
| `positions` | ExecutionEngine | Yes |
| `agent_runs` | ReasoningAgent + pipeline agents | Yes |
| `agent_logs` | All agents via `write_agent_log()` | Yes |
| `agent_grades` | GradeAgent | Yes |
| `agent_heartbeats` | All agents via `write_heartbeat()` | No (heartbeat-only) |
| `trade_performance` | ExecutionEngine | No |
| `vector_memory` | ReasoningAgent | Yes |
| `llm_cost_tracking` | ReasoningAgent | No |
| `factor_ic_history` | ICUpdater | No |

**Rule:** Always use `RETURNING id` for `agent_runs` and `events` — their PKs
are INTEGER sequences, not UUIDs. See `CLAUDE.md` for full INSERT patterns.

---

## InMemoryStore — Postgres Substitute Only

**Use for:** Holding the same data shapes as Postgres tables when the DB is
unavailable. This is NOT a Redis alternative. It has nothing to do with Redis.

**Rule:** `InMemoryStore` is ONLY written when `is_db_available()` is `False`.
It stores the same payload shapes as the DB tables it mirrors so the dashboard
and APIs return consistent structures regardless of DB state.

```python
# Correct routing pattern — used in every agent
if is_db_available():
    await self._db_store_agent_run(...)   # writes to Postgres
else:
    self._mem_store_agent_run(...)        # writes to InMemoryStore
```

**What it mirrors:**

| InMemoryStore field | Mirrors Postgres table |
|--------------------|----------------------|
| `agent_runs` | `agent_runs` |
| `agents` | `agent_heartbeats` (dashboard view) |
| `grade_history` | `agent_grades` |
| `event_history` | `events` |
| `vector_memory` | `vector_memory` |
| `notifications` | Transient (no DB table) |

**What it does NOT mirror:**
- Redis KV keys — if Redis is down, the system has no in-memory fallback
  for prices, kill switch, IC weights, or paper broker state.
- This is intentional: Redis is a hard dependency. InMemoryStore only
  compensates for Postgres loss.

---

## Decision Flowchart — Where Does My Data Go?

```
Is it a message flowing between agents?
  └─ YES → Redis Stream (STREAM_* constant)

Is it shared mutable state needing sub-ms reads?
  └─ YES → Redis KV (REDIS_KEY_* constant)
     └─ Does it need to survive a Redis restart?
           └─ YES → ALSO write to Postgres (dual-write)
           └─ NO  → Redis KV only (prices, locks, budget counters)

Is it a permanent record for audit/history?
  └─ YES → Postgres
     └─ Could DB be down when this is written?
           └─ YES → ALSO write to InMemoryStore as fallback
           └─ NO  → Postgres only

Is it transient UI data that doesn't need to persist?
  └─ YES → InMemoryStore.notifications (max 100 entries, no DB write)
```

---

## Anti-Patterns (Never Do These)

```python
# ❌ Raw string Redis keys — use constants
await redis.set("prices:BTC/USD", ...)          # use REDIS_KEY_PRICES.format(symbol=...)
await redis.get("kill_switch:active")           # use REDIS_KEY_KILL_SWITCH

# ❌ InMemoryStore as Redis fallback
if not redis_available:
    store.add_price("BTC/USD", price)           # wrong — InMemoryStore is DB-only fallback

# ❌ Storing agent-to-agent messages in Redis KV
await redis.set("last_signal", json.dumps(signal))  # wrong — use STREAM_SIGNALS

# ❌ Hardcoded TTL values
await redis.set(key, value, ex=30)              # use REDIS_PRICES_TTL_SECONDS
await redis.set(key, value, ex=90000)           # use REDIS_IC_WEIGHTS_TTL_SECONDS

# ❌ Writing heartbeats directly to Redis
await redis.set(REDIS_AGENT_STATUS_KEY.format(name=...), ...)  # use write_heartbeat()

# ❌ Reading DB-table data from Redis
position = json.loads(await redis.get("paper:positions:BTC/USD"))  # only PaperBroker reads this
```

---

## Redis Unavailability — What Breaks and What Doesn't

| Component | Behavior when Redis is down |
|-----------|---------------------------|
| Kill switch check | Raises exception → order goes to DLQ (safe) |
| Order lock | Raises exception → order rejected (safe) |
| Price cache | Returns None → RiskGuardian skips position (safe-ish) |
| IC weights | Returns None → ReasoningAgent uses empty weights (degraded) |
| Agent heartbeat | Write fails silently → agents show OFFLINE on dashboard |
| LLM budget | Returns 0 → budget unenforced temporarily (acceptable) |
| Paper broker | Cash defaults to 100k, positions default to flat (lossy) |
| Streams (EventBus) | Consumer loop retries with backoff until Redis recovers |

Redis is a **hard infrastructure dependency**. The system is not designed to
run without it. InMemoryStore does not compensate for Redis loss.
