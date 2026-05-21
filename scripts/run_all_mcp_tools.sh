#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${MCP_BASE_URL:-${MCP_URL:-http://localhost:8000/mcp}}"
TOKEN="${MCP_SHARED_TOKEN:-${MCP_TOKEN:-}}"
DRY_RUN_PAYLOADS=false

if [[ "${1:-}" == "--dry-run-payloads" ]]; then
  DRY_RUN_PAYLOADS=true
fi

build_tool_payload() {
  local tool_name="$1"
  local args="${2:-}"
  if [[ -z "$args" ]]; then
    args='{}'
  fi
  jq -nc \
    --arg name "$tool_name" \
    --argjson args "$args" \
    '{
      jsonrpc: "2.0",
      id: 2,
      method: "tools/call",
      params: {
        name: $name,
        arguments: $args
      }
    }'
}

call_tool() {
  local tool_name="$1"
  local args="${2:-}"
  if [[ -z "$args" ]]; then
    args='{}'
  fi
  local payload
  echo "=== tool: ${tool_name} ==="
  if ! payload="$(build_tool_payload "$tool_name" "$args" 2>/dev/null)"; then
    echo "ERROR: failed to build payload for tool ${tool_name}; skipping" >&2
    return 1
  fi
  if ! printf '%s' "$payload" | jq -e '.jsonrpc=="2.0" and .method=="tools/call" and (.params.name|type=="string") and .params.name==$tool_name and (.params.arguments|type=="object") and (.id|type=="number")' --arg tool_name "$tool_name" >/dev/null; then
    echo "ERROR: invalid payload schema for tool ${tool_name}; skipping" >&2
    printf '%s\n' "$payload" | jq . >&2 || true
    return 1
  fi
  if ! printf '%s' "$payload" | jq -e . >/dev/null; then
    echo "ERROR: payload parse validation failed for tool ${tool_name}" >&2
    return 1
  fi

  if [[ "$DRY_RUN_PAYLOADS" == "true" ]]; then
    echo "payload_ok=true"
    return 0
  fi

  if [[ -n "$TOKEN" ]]; then
    curl -sS --fail-with-body "$BASE_URL" \
      -H "content-type: application/json" \
      -H "x-mcp-shared-token: $TOKEN" \
      --data-binary "$payload"
  else
    curl -sS --fail-with-body "$BASE_URL" \
      -H "content-type: application/json" \
      --data-binary "$payload"
  fi
}

failed=0
call_tool get_service_health '{}' || failed=1
call_tool get_debug_state '{}' || failed=1
call_tool get_pnl '{}' || failed=1
call_tool get_trade_feed '{"limit":20}' || failed=1
call_tool get_performance_trends '{}' || failed=1
call_tool get_decisions '{"limit":20}' || failed=1
call_tool get_notifications '{"limit":20}' || failed=1
call_tool get_health_summary '{}' || failed=1
call_tool classify_health '{}' || failed=1
call_tool get_agent_heartbeats '{}' || failed=1
call_tool get_llm_health '{}' || failed=1
call_tool get_agent_grades '{"limit":20}' || failed=1
call_tool get_stream_lag '{}' || failed=1
call_tool get_market_data '{}' || failed=1
call_tool get_positions '{}' || failed=1
call_tool get_config '{}' || failed=1
exit "$failed"
