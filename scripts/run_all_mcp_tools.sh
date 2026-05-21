#!/usr/bin/env bash
set -euo pipefail

MCP_URL="${MCP_URL:-https://trading-control.onrender.com/mcp/}"
BASE_URL="${MCP_BASE_URL:-$MCP_URL}"
TOKEN="${MCP_TOKEN:-${MCP_SHARED_TOKEN:-}}"
DRY_RUN_PAYLOADS=false
SESSION_ID=""

if [[ "${1:-}" == "--dry-run-payloads" ]]; then
  DRY_RUN_PAYLOADS=true
fi

build_init_payload() {
  jq -nc '{
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: {
      protocolVersion: "2025-03-26",
      capabilities: {},
      clientInfo: {
        name: "run-all-mcp-tools",
        version: "1.0.0"
      }
    }
  }'
}

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

print_sanitized_file() {
  local file_path="$1"
  if [[ -s "$file_path" ]]; then
    sed -E 's/(Authorization: Bearer )[[:graph:]]+/\1<redacted>/Ig' "$file_path"
  fi
}

initialize_mcp_session() {
  local init_payload
  local headers_file
  local body_file
  local auth_args=()

  echo "Initializing MCP session..."
  init_payload="$(build_init_payload)"
  headers_file="$(mktemp)"
  body_file="$(mktemp)"

  if [[ -n "$TOKEN" ]]; then
    auth_args=(-H "Authorization: Bearer $TOKEN")
  fi

  if ! curl -sS --fail-with-body \
    -D "$headers_file" \
    -o "$body_file" \
    -X POST "$BASE_URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    "${auth_args[@]}" \
    --data-binary "$init_payload"; then
    echo "Failed to initialize MCP session: initialize request failed" >&2
    echo "Sanitized initialize response headers:" >&2
    print_sanitized_file "$headers_file" >&2 || true
    echo "Sanitized initialize response body:" >&2
    print_sanitized_file "$body_file" >&2 || true
    rm -f "$headers_file" "$body_file"
    return 1
  fi

  SESSION_ID="$({ awk 'BEGIN{IGNORECASE=1} /^mcp-session-id:/ {sub(/\r$/, "", $0); sub(/^[^:]+:[[:space:]]*/, "", $0); print; exit }' "$headers_file"; } || true)"

  if [[ -z "$SESSION_ID" ]]; then
    echo "Failed to initialize MCP session: missing Mcp-Session-Id response header" >&2
    echo "Sanitized initialize response headers:" >&2
    print_sanitized_file "$headers_file" >&2 || true
    echo "Sanitized initialize response body:" >&2
    print_sanitized_file "$body_file" >&2 || true
    rm -f "$headers_file" "$body_file"
    return 1
  fi

  echo "MCP session ready: ${SESSION_ID:0:8}..."
  rm -f "$headers_file" "$body_file"
}

call_tool() {
  local tool_name="$1"
  local args="${2:-}"
  if [[ -z "$args" ]]; then
    args='{}'
  fi
  local payload
  local auth_args=()
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
    auth_args=(-H "Authorization: Bearer $TOKEN")
  fi

  curl -sS --fail-with-body \
    -X POST "$BASE_URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "Mcp-Session-Id: $SESSION_ID" \
    "${auth_args[@]}" \
    --data-binary "$payload"
}

failed=0
if [[ "$DRY_RUN_PAYLOADS" != "true" ]]; then
  initialize_mcp_session || failed=1
fi

if [[ "$failed" -eq 0 ]]; then
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
fi

exit "$failed"
