#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${MCP_BASE_URL:-http://localhost:8000/mcp}"
TOKEN="${MCP_SHARED_TOKEN:-}"

call_tool() {
  local name="$1"
  local args="${2:-{}}"
  local payload
  payload="$(jq -nc --arg name "$name" --argjson args "$args" '{jsonrpc:"2.0",id:2,method:"tools/call",params:{name:$name,arguments:$args}}')"

  if [[ -n "$TOKEN" ]]; then
    curl -sS "$BASE_URL" \
      -H "content-type: application/json" \
      -H "x-mcp-shared-token: $TOKEN" \
      --data-binary "$payload"
  else
    curl -sS "$BASE_URL" \
      -H "content-type: application/json" \
      --data-binary "$payload"
  fi
}

call_tool get_service_health '{}'
call_tool get_debug_state '{}'
call_tool get_pnl '{}'
call_tool get_trade_feed '{"limit":20}'
call_tool get_performance_trends '{}'
call_tool get_decisions '{"limit":20}'
call_tool get_notifications '{"limit":20}'
call_tool get_health_summary '{}'
call_tool classify_health '{}'
call_tool get_agent_heartbeats '{}'
call_tool get_llm_health '{}'
call_tool get_agent_grades '{"limit":20}'
call_tool get_stream_lag '{}'
call_tool get_market_data '{"limit":20}'
call_tool get_positions '{}'
call_tool get_config '{}'
