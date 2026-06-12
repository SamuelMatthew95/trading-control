# Runbook — Trade Failures

## Symptoms
- `trades_failed_total` alert (P1 at >20% of submissions).
- DLQ growth (`redis-cli keys 'dlq:*'` / `GET /dlq`), logs:
  `Message sent to DLQ`, `execution_blocked_*`, `Alpaca order rejected`.

## Impact
Decisions are being made but not executed — strategy and reality diverge.
Failures route to the DLQ (at-least-once semantics), so messages are
preserved, not lost.

## Triage — read ONE failure end-to-end before acting
```bash
# Pull a DLQ entry and get its trace_id + error:
curl -s https://<host>/dlq | python3 -m json.tool | head -40
# Follow the trace: SigNoz → trading.trace_id=<id>, or logs:
kubectl -n trading-control logs deploy/api | grep <trace_id>
```

| Error pattern | Meaning | Action |
|---|---|---|
| `KillSwitchActive` | kill switch is ON | Expected if engaged. If nobody engaged it → who/what set it? `redis-cli get kill_switch:updated_at`. RiskGuardian sets it on daily-loss breach — that is correct behavior, not an incident. |
| `execution_blocked_trading_paused` | learning loop paused trading (Grade F) | Review the proposal that paused it (dashboard → proposals). Deliberate un-pause: `redis-cli del trading_paused` keys only after understanding the grade. |
| broker rejections | order-level problem (size, symbol, market hours) | [broker-unavailable.md](broker-unavailable.md); check min-size rules and market-hours gates |
| `Invalid schema version` in DLQ | producer/consumer drift | a deploy mismatch — roll forward the lagging side |
| `message_processing_timeout_*` | hung processing | [high-latency.md](high-latency.md) |
| pre-execution gate rejections (cooling-off, confidence) | working as designed | not an incident; tune thresholds via proposals, not hotfixes |

## Mitigate
- Failures >20% and cause unclear → kill switch ON while investigating:
  `redis-cli set kill_switch:active 1`.
- **Never bypass risk gates to "make trades go through".** The gates are the
  product.

## Resolve
- Root cause fixed; DLQ replayed (`DLQManager` retries automatically with
  backoff; stuck entries can be re-pushed via `/dlq` tooling) and drained.
- `trades_completed_total/trades_submitted_total` ratio back >95%.
- Kill switch cleared deliberately, first post-clear fill verified.

## Prevent
- Every novel failure mode → entry in
  `docs/troubleshooting/execution-engine.md` + regression test (repo rule).
