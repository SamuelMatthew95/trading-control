# PostgreSQL Schema Audit and v2 Standardization Plan

## 🔴 Issues Found

- **Critical key mismatch:** `agent_runs.id` is `integer`, while related tables store run IDs as both `uuid` (`agent_grades.agent_run_id`) and `varchar` (`agent_logs.agent_run_id`). This prevents reliable FK enforcement and causes brittle casts.
- **Mixed PK strategy across core entities:** IDs are spread across `integer`, `uuid`, and `varchar` with inconsistent defaults (`gen_random_uuid()`, sequence, or none), making joins, ORM typing, and API contracts inconsistent.
- **Timestamp inconsistency:** many tables use `timestamp without time zone` while others use `timestamptz`; global trading/audit workloads should use UTC-aware `timestamptz` consistently.
- **JSON stored as text:** multiple semantic JSON columns are `text` (`agent_runs.decision_json`, `trace_json`, `signal_data`; `insights.payload_json`; `vector_memory.metadata_`; `vector_memory_records.embedding_json`, etc.). This blocks JSON indexing and validation.
- **Missing foreign keys:** core relationships are implicit only. Examples: `agent_logs.agent_run_id` → `agent_runs.id`, `trace_steps.run_id` → `agent_runs.id`, `agent_grades.agent_run_id` → `agent_runs.id`, `feedback_jobs.run_id` → `agent_runs.id`, `insights.run_id` → `agent_runs.id`, `trade_lifecycle.order_id` ↔ `orders.id` type mismatch.
- **Duplicate/overlapping trade models:** `trades` and `trade_lifecycle` both represent trade execution outcomes, with divergent naming and types (`asset` vs `symbol`, `direction` vs `side`, timestamps without tz vs with tz).
- **Unconstrained status/type fields:** many status columns are free-form `varchar` without checks or enums, increasing data quality drift (e.g., `orders.status`, `feedback_jobs.status`, `runs.status`, `trace_steps.feedback_status`).
- **Potentially unsafe defaults:** `agent_logs.agent_run_id` defaults to `'unknown'`; this should be nullable (temporarily) or enforced FK, not synthetic sentinel text.
- **Observability gaps:** trace fields exist but are not uniformly indexed (e.g., missing stable indexing strategy on `trace_id` across `agent_runs`, `agent_logs`, lifecycle tables).
- **Scalability concerns at millions of rows:** large append-only tables (`agent_logs`, `trace_steps`, `events`, `system_metrics`) lack partitioning/retention guidance and time-based index strategy.

---

## 🟡 Recommended Schema (cleaned version)

Design choice: **UUID as canonical identifier for domain entities** (`agent_runs`, `orders`, `trade_lifecycle`, etc.), with additive `legacy_id` columns only during migration. This supports distributed writes and consistent cross-service contracts.

```sql
-- Required extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- Optional if you later move embeddings to pgvector
-- CREATE EXTENSION IF NOT EXISTS vector;

-- Optional enums (can be CHECK constraints if you prefer)
DO $$ BEGIN
  CREATE TYPE order_side AS ENUM ('buy','sell');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE order_status AS ENUM ('pending','accepted','partially_filled','filled','cancelled','rejected','expired');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE run_status AS ENUM ('queued','running','completed','failed','cancelled');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS agent_runs_v2 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  legacy_id INTEGER UNIQUE,
  task_id TEXT,
  strategy_id TEXT,
  instance_id UUID REFERENCES agent_instances(id) ON DELETE SET NULL,
  trace_id TEXT NOT NULL,
  decision JSONB,
  trace JSONB,
  signal_data JSONB,
  action TEXT,
  confidence DOUBLE PRECISION,
  primary_edge TEXT,
  risk_factors JSONB,
  size_pct DOUBLE PRECISION,
  stop_atr_x DOUBLE PRECISION,
  rr_ratio DOUBLE PRECISION,
  latency_ms INTEGER,
  cost_usd DOUBLE PRECISION,
  fallback BOOLEAN NOT NULL DEFAULT FALSE,
  status run_status NOT NULL DEFAULT 'completed',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS agent_logs_v2 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_run_id UUID NOT NULL REFERENCES agent_runs_v2(id) ON DELETE CASCADE,
  trace_id TEXT NOT NULL,
  log_type TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trace_steps_v2 (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  agent_run_id UUID NOT NULL REFERENCES agent_runs_v2(id) ON DELETE CASCADE,
  node_name TEXT NOT NULL,
  step_type TEXT,
  tool_name TEXT,
  tool_call JSONB,
  transcript TEXT,
  is_hallucination BOOLEAN,
  coach_reason TEXT,
  is_starred BOOLEAN,
  override_payload JSONB,
  promoted_rule_key TEXT,
  feedback_status TEXT,
  tokens_used INTEGER,
  context_limit INTEGER,
  token_cost_usd DOUBLE PRECISION,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_grades_v2 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id UUID,
  agent_run_id UUID NOT NULL REFERENCES agent_runs_v2(id) ON DELETE CASCADE,
  grade_type TEXT NOT NULL,
  score NUMERIC(8,4) NOT NULL,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  feedback TEXT,
  schema_version TEXT NOT NULL DEFAULT 'v3',
  source TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders_v2 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  legacy_id TEXT UNIQUE,
  strategy_id TEXT NOT NULL,
  agent_run_id UUID REFERENCES agent_runs_v2(id) ON DELETE SET NULL,
  symbol TEXT NOT NULL,
  side order_side NOT NULL,
  qty NUMERIC(20,8) NOT NULL,
  price NUMERIC(20,8) NOT NULL,
  status order_status NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  broker_order_id TEXT,
  external_order_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  filled_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS trade_lifecycle_v2 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id UUID REFERENCES orders_v2(id) ON DELETE SET NULL,
  agent_run_id UUID REFERENCES agent_runs_v2(id) ON DELETE SET NULL,
  symbol TEXT NOT NULL,
  side order_side NOT NULL,
  qty NUMERIC(20,8),
  entry_price NUMERIC(20,8),
  exit_price NUMERIC(20,8),
  pnl NUMERIC(20,8),
  pnl_percent NUMERIC(20,8),
  signal_trace_id TEXT,
  decision_trace_id TEXT,
  execution_trace_id TEXT,
  grade_trace_id TEXT,
  reflection_trace_id TEXT,
  status TEXT NOT NULL DEFAULT 'signal',
  filled_at TIMESTAMPTZ,
  graded_at TIMESTAMPTZ,
  reflected_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system_metrics_v2 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  metric_name TEXT NOT NULL,
  metric_value DOUBLE PRECISION NOT NULL,
  labels JSONB NOT NULL DEFAULT '{}'::jsonb,
  tags JSONB NOT NULL DEFAULT '{}'::jsonb,
  metric_unit TEXT,
  source TEXT,
  trace_id TEXT,
  observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS vector_memory_v2 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content TEXT NOT NULL,
  embedding JSONB,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  outcome JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Core indexes (time-series + tracing + FK lookups)
CREATE INDEX IF NOT EXISTS idx_agent_runs_v2_trace_created ON agent_runs_v2 (trace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_logs_v2_run_created ON agent_logs_v2 (agent_run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_logs_v2_trace_created ON agent_logs_v2 (trace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trace_steps_v2_run_created ON trace_steps_v2 (agent_run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_v2_symbol_created ON orders_v2 (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_v2_run_created ON orders_v2 (agent_run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_lifecycle_v2_order ON trade_lifecycle_v2 (order_id);
CREATE INDEX IF NOT EXISTS idx_trade_lifecycle_v2_created ON trade_lifecycle_v2 (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_system_metrics_v2_name_time ON system_metrics_v2 (metric_name, observed_at DESC);
```

---

## 🟢 Migration Plan

### Phase A — Safe additive migrations (online-first)

```sql
-- 1) Add UUID shadow keys + timestamptz shadow columns
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS id_uuid UUID;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS created_at_tz TIMESTAMPTZ;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS updated_at_tz TIMESTAMPTZ;

ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS id_uuid UUID;
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS agent_run_uuid UUID;
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS payload_jsonb JSONB;
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS created_at_tz TIMESTAMPTZ;

ALTER TABLE agent_grades ADD COLUMN IF NOT EXISTS agent_run_uuid UUID;
ALTER TABLE trace_steps ADD COLUMN IF NOT EXISTS agent_run_uuid UUID;
ALTER TABLE feedback_jobs ADD COLUMN IF NOT EXISTS run_uuid UUID;
ALTER TABLE insights ADD COLUMN IF NOT EXISTS run_uuid UUID;

ALTER TABLE orders ADD COLUMN IF NOT EXISTS id_uuid UUID;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_at_tz TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS filled_at_tz TIMESTAMPTZ;

ALTER TABLE trade_lifecycle ADD COLUMN IF NOT EXISTS order_uuid UUID;
ALTER TABLE trade_lifecycle ADD COLUMN IF NOT EXISTS agent_run_uuid UUID;

ALTER TABLE vector_memory ADD COLUMN IF NOT EXISTS metadata JSONB;
ALTER TABLE vector_memory ADD COLUMN IF NOT EXISTS outcome_jsonb JSONB;
ALTER TABLE system_metrics ADD COLUMN IF NOT EXISTS labels_jsonb JSONB;
```

```sql
-- 2) Backfill shadow columns safely
UPDATE agent_runs
SET id_uuid = COALESCE(id_uuid, gen_random_uuid()),
    created_at_tz = COALESCE(created_at_tz, created_at AT TIME ZONE 'UTC', now()),
    updated_at_tz = COALESCE(updated_at_tz, now())
WHERE id_uuid IS NULL OR created_at_tz IS NULL OR updated_at_tz IS NULL;

-- Cast text -> jsonb only when valid, fallback to wrapped object
UPDATE agent_logs
SET payload_jsonb = COALESCE(
      payload_jsonb,
      CASE WHEN payload IS NULL THEN '{}'::jsonb
           WHEN left(trim(payload), 1) IN ('{','[') THEN payload::jsonb
           ELSE jsonb_build_object('message', payload)
      END
    ),
    created_at_tz = COALESCE(created_at_tz, created_at, "timestamp", now()),
    id_uuid = COALESCE(id_uuid, gen_random_uuid())
WHERE payload_jsonb IS NULL OR created_at_tz IS NULL OR id_uuid IS NULL;

UPDATE agent_logs l
SET agent_run_uuid = r.id_uuid
FROM agent_runs r
WHERE l.agent_run_uuid IS NULL
  AND l.agent_run_id ~ '^[0-9]+$'
  AND r.id = l.agent_run_id::integer;

UPDATE agent_grades g
SET agent_run_uuid = r.id_uuid
FROM agent_runs r
WHERE g.agent_run_uuid IS NULL
  AND g.agent_run_id::text = r.id_uuid::text;

UPDATE trace_steps t
SET agent_run_uuid = r.id_uuid
FROM agent_runs r
WHERE t.agent_run_uuid IS NULL
  AND t.run_id = r.id;

UPDATE feedback_jobs f
SET run_uuid = r.id_uuid
FROM agent_runs r
WHERE f.run_uuid IS NULL
  AND f.run_id = r.id;

UPDATE insights i
SET run_uuid = r.id_uuid
FROM agent_runs r
WHERE i.run_uuid IS NULL
  AND i.run_id = r.id;

UPDATE orders
SET id_uuid = COALESCE(id_uuid, gen_random_uuid()),
    created_at_tz = COALESCE(created_at_tz, created_at AT TIME ZONE 'UTC', now()),
    filled_at_tz = COALESCE(filled_at_tz, filled_at AT TIME ZONE 'UTC')
WHERE id_uuid IS NULL OR created_at_tz IS NULL;

UPDATE trade_lifecycle tl
SET order_uuid = o.id_uuid
FROM orders o
WHERE tl.order_uuid IS NULL
  AND tl.order_id::text = o.id_uuid::text;

UPDATE vector_memory
SET metadata = COALESCE(
      metadata,
      CASE WHEN metadata_ IS NULL THEN '{}'::jsonb
           WHEN left(trim(metadata_), 1) IN ('{','[') THEN metadata_::jsonb
           ELSE jsonb_build_object('raw', metadata_)
      END
    ),
    outcome_jsonb = COALESCE(
      outcome_jsonb,
      CASE WHEN outcome IS NULL THEN NULL
           WHEN left(trim(outcome), 1) IN ('{','[') THEN outcome::jsonb
           ELSE jsonb_build_object('raw', outcome)
      END
    )
WHERE metadata IS NULL OR (outcome IS NOT NULL AND outcome_jsonb IS NULL);

UPDATE system_metrics
SET labels_jsonb = COALESCE(
      labels_jsonb,
      CASE WHEN labels IS NULL THEN '{}'::jsonb
           WHEN left(trim(labels), 1) IN ('{','[') THEN labels::jsonb
           ELSE jsonb_build_object('raw', labels)
      END
    )
WHERE labels_jsonb IS NULL;
```

```sql
-- 3) Add NOT VALID FKs first, then validate (safer on hot tables)
ALTER TABLE agent_logs
  ADD CONSTRAINT fk_agent_logs_run_uuid
  FOREIGN KEY (agent_run_uuid) REFERENCES agent_runs(id_uuid) NOT VALID;

ALTER TABLE trace_steps
  ADD CONSTRAINT fk_trace_steps_run_uuid
  FOREIGN KEY (agent_run_uuid) REFERENCES agent_runs(id_uuid) NOT VALID;

ALTER TABLE feedback_jobs
  ADD CONSTRAINT fk_feedback_jobs_run_uuid
  FOREIGN KEY (run_uuid) REFERENCES agent_runs(id_uuid) NOT VALID;

ALTER TABLE insights
  ADD CONSTRAINT fk_insights_run_uuid
  FOREIGN KEY (run_uuid) REFERENCES agent_runs(id_uuid) NOT VALID;

ALTER TABLE trade_lifecycle
  ADD CONSTRAINT fk_trade_lifecycle_order_uuid
  FOREIGN KEY (order_uuid) REFERENCES orders(id_uuid) NOT VALID;

ALTER TABLE agent_logs VALIDATE CONSTRAINT fk_agent_logs_run_uuid;
ALTER TABLE trace_steps VALIDATE CONSTRAINT fk_trace_steps_run_uuid;
ALTER TABLE feedback_jobs VALIDATE CONSTRAINT fk_feedback_jobs_run_uuid;
ALTER TABLE insights VALIDATE CONSTRAINT fk_insights_run_uuid;
ALTER TABLE trade_lifecycle VALIDATE CONSTRAINT fk_trade_lifecycle_order_uuid;
```

```sql
-- 4) Create indexes concurrently for live traffic
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_agent_runs_id_uuid ON agent_runs(id_uuid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_agent_runs_trace_created ON agent_runs(trace_id, created_at_tz DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_agent_logs_run_created ON agent_logs(agent_run_uuid, created_at_tz DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_agent_logs_trace_created ON agent_logs(trace_id, created_at_tz DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_trace_steps_run_created ON trace_steps(agent_run_uuid, created_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_feedback_jobs_run_uuid ON feedback_jobs(run_uuid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_insights_run_uuid_created ON insights(run_uuid, created_at DESC);
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_orders_id_uuid ON orders(id_uuid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_orders_symbol_created ON orders(symbol, created_at_tz DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_trade_lifecycle_order_uuid_created ON trade_lifecycle(order_uuid, created_at DESC);
```

### Phase B — Controlled cutover (breaking, scheduled)

```sql
-- In a deployment window, swap app reads/writes to *_uuid and *_tz columns.
-- Then enforce constraints and rename columns.

ALTER TABLE agent_runs ALTER COLUMN id_uuid SET NOT NULL;
ALTER TABLE agent_logs ALTER COLUMN agent_run_uuid SET NOT NULL;

-- Example rename sequence
ALTER TABLE agent_runs RENAME COLUMN id TO legacy_id_int;
ALTER TABLE agent_runs RENAME COLUMN id_uuid TO id;

ALTER TABLE agent_logs RENAME COLUMN agent_run_id TO legacy_agent_run_id;
ALTER TABLE agent_logs RENAME COLUMN agent_run_uuid TO agent_run_id;
ALTER TABLE agent_logs RENAME COLUMN payload TO legacy_payload;
ALTER TABLE agent_logs RENAME COLUMN payload_jsonb TO payload;
ALTER TABLE agent_logs RENAME COLUMN created_at TO legacy_created_at;
ALTER TABLE agent_logs RENAME COLUMN created_at_tz TO created_at;
```

### Phase C — Data quality fixes and normalization

```sql
-- Normalize status values before adding enums/checks
UPDATE orders SET status = lower(status);
UPDATE orders SET side = lower(side);

-- Example hard checks (post-cleanup)
ALTER TABLE orders
  ADD CONSTRAINT chk_orders_side CHECK (side IN ('buy','sell')) NOT VALID;
ALTER TABLE orders VALIDATE CONSTRAINT chk_orders_side;

-- Fill null timestamps with deterministic values
UPDATE feedback_jobs SET created_at = COALESCE(created_at, now() AT TIME ZONE 'UTC');
UPDATE insights SET created_at = COALESCE(created_at, now() AT TIME ZONE 'UTC');
```

---

## 🔵 Code Changes Needed

- **Domain model typing updates:**
  - Change `agent_run_id` type from `int`/`str` to `UUID` in models for logs, grades, insights, feedback jobs, trace steps.
  - Introduce temporary dual-read/dual-write for migration window (`run_id` + `run_uuid`).
- **ORM schema updates:**
  - Map JSON text columns to native JSONB (`payload`, `decision`, `trace`, `signal_data`, memory metadata).
  - Convert datetime fields to timezone-aware objects only (`DateTime(timezone=True)` in SQLAlchemy).
- **Query updates:**
  - Update joins to use UUID FK columns (`agent_logs.agent_run_id` → `agent_runs.id` after cutover).
  - Route tracing queries to new indexes (`trace_id, created_at DESC`).
- **API contract changes:**
  - Any endpoint returning run/order IDs must emit UUID strings.
  - Accept legacy integer IDs during transition via compatibility layer (lookup by `legacy_id`).
- **Validation hardening:**
  - Enforce allowed status/side values in application validators before DB CHECK/enum cutover.
- **Backfill job/ops changes:**
  - Add one-time migration jobs for JSON parse fallback handling and orphan detection.
  - Add metrics on orphaned references and cast failures before making FKs strict.
- **Observability and scale:**
  - Add correlation IDs (`trace_id`, `run_id`) to structured logs and all write paths.
  - Implement retention/partition policy for `agent_logs`, `events`, and `system_metrics` (e.g., monthly partitions + TTL/archive jobs).

