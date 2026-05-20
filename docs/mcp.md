# MCP Server (How to Use)

This service exposes a **read-only** remote MCP endpoint at:

- `https://trading-control.onrender.com/mcp`

Use that exact URL in Claude Code / Claude MCP connector settings.

## What tools are available

- `get_service_health`
- `get_debug_state`
- `get_pnl`
- `get_trade_feed`
- `get_performance_trends`
- `get_decisions`
- `get_notifications`
- `get_health_summary`
- `classify_health`
- `get_agent_heartbeats`
- `get_llm_health`
- `get_agent_grades`
- `get_stream_lag`
- `get_market_data`
- `get_positions`
- `get_config`

These tools are telemetry-only. They do **not** place trades or mutate runtime config.


## Tool parameters and response contract

All new telemetry tools return a structured envelope:

```json
{
  "ok": true,
  "degraded": false,
  "source": "redis|db|in_memory|mixed|settings|in_process",
  "generated_at": "ISO-8601",
  "data": {}
}
```

When a datasource is unavailable, `degraded` is `true` and `reason` is included.

### Stability contract (to avoid future MCP breakage)

When adding or changing MCP read tools, keep these rules:

1. **Always return the envelope** (`ok`, `degraded`, `source`, `generated_at`, `data`) even in fallback mode.
2. **Never return legacy top-level `status` shapes** for telemetry reads.
3. **Do not probe DB first in memory mode** — if `is_db_available()` is false, return `source: "in_memory"` directly.
4. **Mark degraded explicitly** with a machine-readable `reason` when sanitizing or falling back.
5. **Sanitize malformed numerics** to `null`/`None` (not exceptions), and include degradation reason when sanitization was required.
6. **Do not expose secrets**; config/health tools must keep token/key fields redacted.

These are enforced by MCP/API tests and are required for operator dashboards and agent tooling compatibility.

### Parameters

- `get_agent_grades(limit=20, agent_name=null, since=null)`
  - `limit` max `100`
  - `since` must be ISO-8601 when provided
- `get_market_data(symbol=null, limit=20)`
  - `limit` max `100`

### Notes

- `get_agent_heartbeats` uses Redis first, then DB heartbeat fallback, then in-memory fallback.
- `get_config` is redacted and never returns raw credentials/tokens.

## Authentication (current behavior)

Current app behavior is **standard unauthenticated MCP mount**:

- `/mcp` is mounted directly to the FastMCP app.
- **All HTTP requests to `/mcp` are forwarded directly to FastMCP** (no bearer-token middleware in front).
- No bearer token is required for MCP requests right now.

If token auth is re-enabled in code later, this document should be updated in the same PR.

## Claude connector setup (normal)

Use these settings:

- **Remote MCP server URL**: `https://trading-control.onrender.com/mcp`
- **Auth/OAuth fields**: leave blank

Then test with a simple prompt, for example:

- `Use the trading-control MCP connector. List available tools.`

## Quick checks

### Endpoint checks

```bash
curl -i https://trading-control.onrender.com/mcp
curl -i https://trading-control.onrender.com/api/health
curl -i https://trading-control.onrender.com/api/dashboard/debug/state
curl -i https://trading-control.onrender.com/api/dashboard/pnl
```

Expected:

- `/mcp` returns an MCP-compatible response (and should not require auth in current config).
- REST health/dashboard routes continue returning normal API responses.

### Local quality check for MCP module

```bash
python -m compileall api
ruff check api
pytest tests/api/test_mcp_server.py -q
```
