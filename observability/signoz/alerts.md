# Alert Recommendations

Create these in SigNoz → Alerts. Severities follow a simple contract:
**P1** pages immediately (money or availability at risk), **P2** notifies a
channel (degradation), **P3** is a daily-digest ticket.

| # | Alert | Query / condition | Window | Severity | Why this threshold |
|---|---|---|---|---|---|
| 1 | API down | absence of `http_server_duration_count` for the service | 2 min | P1 | `/health` is scraped externally; total silence = process dead |
| 2 | Trade failures spiking | rate(`trades_failed_total`) > 0.2/s OR failures/submitted > 20% | 5 min | P1 | normal failure rate is ~0; 20% means broker or risk-gate breakage |
| 3 | Daily loss limit | `daily_pnl` < −2% of `account_balance` | instant | P1 | mirrors the platform's own daily-loss rule; if it fires, verify the kill switch engaged |
| 4 | Broker latency | p95(`broker_api_latency{operation="place_order"}`) > 5000 ms | 10 min | P2 | >5s order placement breaks the <5s signal→fill SLO |
| 5 | Broker call failures | rate(`broker_api_latency_count{success="false"}`) > 0.1/s | 5 min | P2 | sustained API errors → check Alpaca status / credentials |
| 6 | Agent stalled | absence of `agent_process_duration{agent=X}` for any pipeline agent | 15 min | P2 | agents heartbeat through processing; silence while ticks flow = stuck consumer |
| 7 | Event retries climbing | rate(`retry_count`) > 0.5/s | 10 min | P2 | poison messages heading for the DLQ; inspect `dlq:*` |
| 8 | Error burst | rate(`error_count`) > 1/s | 5 min | P2 | any component erroring once per second is degraded |
| 9 | HTTP 5xx | 5xx / total requests > 2% | 10 min | P2 | dashboard/API consumers visibly affected |
| 10 | DB queries slow | p95(`database_query_duration`) > 500 ms | 15 min | P3 | Render Postgres starter-plan saturation indicator |
| 11 | No signals during market hours | rate(`signals_generated_total`) == 0 while crypto ticks expected | 30 min | P3 | price poller or signal generator quietly wedged |
| 12 | Win rate collapse | `win_rate` < 0.30 with ≥ 20 trades | 1 day | P3 | strategy degradation — feed to ReflectionAgent review |

## Governance & cost alerts

Telemetry-about-telemetry — schema drift and ingest cost. Metric names come from
the telemetry governance layer (`docs/platform/telemetry-governance.md`).

| # | Alert | Query / condition | Window | Severity | Why |
|---|---|---|---|---|---|
| 13 | Schema drift — unknown attribute | `rate(telemetry_schema_drift_total{drift_kind="unknown_key"}) > 0` | 1h | P2 | a `trading.*` attribute reached prod that isn't in `TELEMETRY_SCHEMA` — unbudgeted cardinality |
| 14 | Cardinality budget exceeded | `rate(telemetry_schema_drift_total{drift_kind="budget_exceeded"}) > 0` | 6h | P2 | a registered attribute blew past its declared budget |
| 15 | Cost per trade anomaly | `cost_per_business_event > 3 × rolling_7d_median` | 6h | P2 | telemetry spend rising while trades are flat — ingest bloat |
| 16 | Active series growth | `(signoz_active_time_series - offset 24h) / offset 24h > 0.25` | 24h | P2 | structural cardinality creep |

Routing: SigNoz supports Slack/PagerDuty/webhook channels — point P1 at the
pager, P2 at the team channel, P3 at a digest. Every alert should link the
matching runbook in `docs/runbooks/`.
