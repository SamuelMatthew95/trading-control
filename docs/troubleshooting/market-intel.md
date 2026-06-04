# Market-Intel Perception Tools Troubleshooting

The reasoning agent's live perception tools in `api/services/market_intel.py`
— `fetch_order_book_depth`, `fetch_news_sentiment`, `compute_cross_asset_correlation`,
`fetch_macro_regime` — each call the Alpaca data API and degrade to `{}` (recorded
as the tool's `success: false`) when their data is unavailable.

## `check_cross_asset_correlation` returned `success: false` on every decision

**Symptom:** All sampled decisions showed the correlation tool returning
`success: false` — never producing a correlation, while the sibling tools
worked.

**Root cause:** NOT a DB table and NOT a missing Redis producer (the
`correlation:{symbol}` key is a self-populating cache). `_fetch_bars` requested
HISTORICAL bars from Alpaca with only `symbols` / `timeframe` / `limit` and **no
`start` window**. Alpaca returns the OLDEST bars (ascending) in that case, so the
recent-returns correlation got stale/empty data and the tool degraded to `{}`
every time — unlike the SignalGenerator bootstrap, whose SDK request always
passes `start`/`end`.

**Fix:** `_fetch_bars` now sends a recent `start` (`now - _CORRELATION_BARS*4`
minutes) and `sort=desc` so Alpaca returns the LATEST bars
(`api/services/market_intel.py`).

**Note:** equities still have no 1-minute bars outside market hours, so equity
correlation legitimately returns `{}` overnight. And all three tools return `{}`
when `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` are unset — if order-book/news also
show `success: false`, the keys are missing rather than the request being
malformed.

**Regression test:** `tests/api/test_market_intel.py::test_correlation_request_uses_recent_start_window`

## `fetch_macro_regime` was advertised to the LLM but never ran (no `×` count)

**Symptom:** Tool governance listed `fetch_macro_regime` under "TOOLS THE AI MAY
USE" with a seeded `α+0.40` prior but **no call count** — every sibling
perception tool showed `×N`, this one showed nothing. It was eligible for the
reasoning prompt yet no code path ever invoked it, so it could never earn alpha,
feed a decision, or be graded. Pure catalog decoration.

**Root cause:** `TOOL_MACRO_REGIME` existed in `default_tools()` (so it was
selected into the prompt) but had **no implementation** in `market_intel.py` and
was **not in the reasoning agent's `_gather_market_intel` fetch list** — unlike
order-book / news / correlation, which are both implemented and invoked.

**Fix:** Implemented `fetch_macro_regime(symbol, redis)` — derives a
risk-on / risk-off / neutral posture from a benchmark's recent trend
(`SYMBOL_BTC_USD` for crypto, `SYMBOL_SPY` for equities) and wired it into
`ReasoningAgent._gather_market_intel` + the `_call_llm` prompt payload
(`FieldName.MACRO_REGIME`). It uses **daily** bars (not 1-min) via
`_fetch_recent_closes`, so unlike the correlation tool it stays populated outside
regular trading hours. Redis-cached 300 s (`REDIS_KEY_MACRO_REGIME`).

**Regression test:** `tests/api/test_market_intel.py::test_macro_regime_risk_on_when_benchmark_trends_up`
