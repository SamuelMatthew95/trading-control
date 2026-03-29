# Agent Implementation Guide

## Adding a New Agent

1. Create api/agents/your_agent.py extending MultiStreamAgent
2. Add a row to the agent_pool seed migration with a hardcoded UUID
3. Register it in api/main.py agent initialization
4. Add it to the stream chain in CLAUDE.md architecture section
5. Add tests in tests/agents/test_your_agent.py
6. Update CHANGELOG.md

## Agent Startup Sequence

Every agent must do these things in order on startup:
1. Load its own UUID from agent_pool table by name
2. Write WAITING status to Redis and agent_heartbeats
3. Log startup message with stream name it is listening on
4. Enter XREAD loop

## Stream Names (never change these)

market_events → signals → decisions → graded_decisions

## Trace ID Rules

- Extract from incoming event payload field "trace_id"
- If missing (first event in chain), generate uuid4() in price_poller only
- Pass through to every agent_logs INSERT
- Pass through to every outgoing stream payload
- Never generate a new trace_id inside an agent
