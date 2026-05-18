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

These tools are telemetry-only. They do **not** place trades or mutate runtime config.

## Authentication (current behavior)

Current app behavior is **standard unauthenticated MCP mount**:

- `/mcp` is mounted directly to the FastMCP app.
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
