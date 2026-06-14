# Service Level Objectives (SLOs)

Alerts answer "is something wrong **now**?"; SLOs answer "how close are we to
**structural** failure?". This is the canonical SLO spec — create these in SigNoz
(Alerts → multi-window burn-rate). Design: `docs/platform/telemetry-governance.md` §4.

## Calibration gate (READ FIRST)

Targets marked **CALIBRATE** are framework placeholders, **not** final. The
repo's own data shows naive targets are wrong (reasoning-agent P99 ≈ 66.8s, so a
"95% < 2s" agent SLO would burn budget forever). Before a target goes live, pull
30 days of the SLI's percentiles from SigNoz and set it at a defensible multiple
of **measured P99** — the same discipline that sized the RED buckets above P99.

## SLOs

| SLO | SLI (existing metric) | Objective | Window | Target | Status |
|---|---|---|---|---|---|
| Trade execution latency | `broker_api_latency{trading.operation="place_order"}` p99 | 99.9% under target | 30d | **CALIBRATE** — 150ms is unrealistic for a broker round-trip; the alert uses 5000ms | scaffold |
| Order success rate | `1 − rate(trades_failed_total) / rate(trades_submitted_total)` | 99% | 30d | **CALIBRATE** | scaffold |
| Agent decision latency | `agent_process_duration{trading.agent="REASONING_AGENT"}` p95 | 95% under target | 30d | **CALIBRATE** — LLM-bound; P99 ≈ 66.8s → likely 10–30s, or split fast/LLM paths | scaffold |
| API availability | non-5xx share of `http_server_duration_count` | 99.9% | 30d | 99.9% | scaffold |

Stream freshness (99% msgs < 2s lag) is **deferred** — no consumer-lag histogram
is emitted today; use `alerts.md` #6 (agent stalled) / #11 (no signals) until a
lag metric is instrumented.

## Error budgets & burn-rate alerts

For a target `T` over 30 days the error budget is `1 − T` of the window
(99.9% → 43m; 99% → 7.2h; 95% → 36h). Page on **fast burn**, ticket on **slow
burn** (Google-SRE multi-window, multi-burn-rate):

| Severity | Burn rate | Long window | Short window | Budget consumed |
|---|---|---|---|---|
| P1 (page) | 14.4× | 1h | 5m | ~2% of the 30d budget in 1h |
| P2 (ticket) | 6× | 6h | 30m | ~5% in 6h |
| P3 (digest) | 1× | 24h | 1h | trend |

A burn-rate alert fires only when **both** the long and short window exceed the
threshold — the short window stops it flapping after recovery. Each SLO links its
runbook in `docs/runbooks/`.
