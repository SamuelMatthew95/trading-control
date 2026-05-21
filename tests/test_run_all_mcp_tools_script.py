from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def test_run_all_mcp_tools_emits_single_valid_json_per_request(tmp_path: Path) -> None:
    calls_file = tmp_path / "calls.jsonl"
    curl_stub = tmp_path / "curl"
    curl_stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "payload=''\n"
        "headers_file=''\n"
        "body_file=''\n"
        "while [[ $# -gt 0 ]]; do\n"
        '  if [[ "$1" == \'--data-binary\' ]]; then payload="$2"; shift 2; continue; fi\n'
        '  if [[ "$1" == \'-D\' ]]; then headers_file="$2"; shift 2; continue; fi\n'
        '  if [[ "$1" == \'-o\' ]]; then body_file="$2"; shift 2; continue; fi\n'
        "  shift\n"
        "done\n"
        'jq -e . >/dev/null <<<"$payload"\n'
        # For the initialize request, write session header + body to files
        'if [[ -n "$headers_file" ]]; then\n'
        '  printf "HTTP/1.1 200 OK\\r\\nmcp-session-id: test-session-123\\r\\n\\r\\n" > "$headers_file"\n'
        "fi\n"
        'body=\'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26","capabilities":{}}}\'\n'
        'if [[ -n "$body_file" ]]; then\n'
        '  echo "$body" > "$body_file"\n'
        "else\n"
        # Only record payload and echo for tool calls (not initialize)
        "  method=$(jq -r '.method // empty' <<<\"$payload\")\n"
        '  if [[ "$method" == "tools/call" ]]; then\n'
        "    count=$(jq -s 'length' <<<\"$payload\")\n"
        "    [[ \"$count\" == '1' ]]\n"
        '    echo "$payload" >> "$CALLS_FILE"\n'
        "  fi\n"
        '  echo \'{"jsonrpc":"2.0","id":2,"result":{}}\'\n'
        "fi\n"
    )
    curl_stub.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    env["CALLS_FILE"] = str(calls_file)
    env["MCP_BASE_URL"] = "http://localhost:8000/mcp"

    result = subprocess.run(
        ["bash", "scripts/run_all_mcp_tools.sh"],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    payloads = [json.loads(line) for line in calls_file.read_text().splitlines() if line.strip()]
    assert payloads
    expected_names = {
        "get_service_health",
        "get_debug_state",
        "get_pnl",
        "get_trade_feed",
        "get_performance_trends",
        "get_decisions",
        "get_notifications",
        "get_health_summary",
        "classify_health",
        "get_agent_heartbeats",
        "get_llm_health",
        "get_agent_grades",
        "get_stream_lag",
        "get_market_data",
        "get_positions",
        "get_config",
    }
    seen_names = set()
    for payload in payloads:
        assert payload["jsonrpc"] == "2.0"
        assert payload["method"] == "tools/call"
        assert isinstance(payload["id"], int)
        seen_names.add(payload["params"]["name"])
        assert isinstance(payload["params"]["arguments"], dict)
    assert seen_names == expected_names


def test_run_all_mcp_tools_dry_run_payloads_valid() -> None:
    result = subprocess.run(
        ["bash", "scripts/run_all_mcp_tools.sh", "--dry-run-payloads"],
        cwd=str(Path(__file__).parent.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = f"{result.stdout}\n{result.stderr}"
    assert "Parse error" not in output
    assert "Extra data" not in output
    assert "server-error" not in output
