# MCP Server (Production Guide)

This service exposes a **read-only** MCP endpoint mounted under:

- `https://trading-control.onrender.com/mcp`

## What it exposes

Allowed tools:

- `get_service_health`
- `get_debug_state`
- `get_pnl`
- `get_trade_feed`
- `get_performance_trends`
- `get_decisions`
- `get_notifications`
- `get_health_summary`
- `classify_health`

These tools are telemetry only. They do **not** place trades, toggle kill switch, mutate proposals, or update env/config.

## Authentication

Set this Render environment variable for production:

```text
MCP_SHARED_TOKEN=<strong random token>
```

Behavior:

- If `MCP_SHARED_TOKEN` is set: all `/mcp` HTTP requests require
  `Authorization: Bearer <token>`.
- If `MCP_SHARED_TOKEN` is unset: endpoint remains read-only but unauthenticated.

## Connector settings (Claude)

- Remote MCP server URL: `https://trading-control.onrender.com/mcp`
- OAuth fields: leave blank unless OAuth is explicitly implemented.
- If connector UI cannot attach bearer headers, use an auth-capable integration path.

## Deployment checks

After deploy, run:

```bash
curl -i https://trading-control.onrender.com/mcp
curl -i https://trading-control.onrender.com/api/health
curl -i https://trading-control.onrender.com/api/dashboard/debug/state
curl -i https://trading-control.onrender.com/api/dashboard/pnl
```

If token is configured:

```bash
curl -i https://trading-control.onrender.com/mcp
curl -i -H "Authorization: Bearer $MCP_SHARED_TOKEN" https://trading-control.onrender.com/mcp
```

Expected:

- no token → `401`
- valid token → not `404`, MCP-compatible response

## Local checks

```bash
python -m compileall api
ruff check api
pytest tests/api/test_mcp_server.py -q
```
