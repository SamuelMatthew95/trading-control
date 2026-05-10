# Dashboard Read Source-Selection Architecture

## Design

- **Route = HTTP/API boundary only**
- **DashboardReadSelector = source decision** (DB source, runtime source, empty/default source)
- **DashboardReadService = payload construction** for DB/runtime/empty responses

Routes in `api/routes/dashboard_v2.py` must not:
- call `get_runtime_store()`
- call `is_db_available()`
- build inline empty payloads
- implement DB/runtime try-except source choice

Runtime source is an intentional source selection when DB is unavailable/degraded.
It is not route-local fallback logic.

Empty/default source is a named schema-compatible payload helper in `DashboardReadService`.

## Frontend/Backend contract

Dashboard response shapes must remain stable for frontend consumers.
Main endpoint families:
- snapshot/state
- prices
- orders/positions/portfolio/pnl/trade-feed/lifecycle
- agents/agent-runs/notifications
- system metrics/system health/stream lag/flow status
- learning grades/ic-weights/proposals/reflections/loop
- operator reads (trace/history/performance/agent-instances/challengers)

## Checklist for new dashboard read routes

1. Add `db_*` source helper in `DashboardReadService`
2. Add `runtime_*` source helper in `DashboardReadService`
3. Add `empty_*` source helper in `DashboardReadService`
4. Route calls `DashboardReadSelector.select_resource(...)`
5. Add/extend static guardrail route test
6. Add runtime/default behavior test where practical
7. Run grep audit before merge:
   - `get_runtime_store`
   - `is_db_available`
   - `except Exception`
   - `fallback`
   - `return []`
   - `"source": "memory"`
   - `"source": "db"`
   - `TODO`
