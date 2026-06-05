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

## `check_cross_asset_correlation` STILL 100% err — daily fallback only checked the base symbol

**Symptom:** Even after the `start`-window fix and the daily-bar fallback, the
tool read `41× · 0 ok · 100% err` on the governance panel while the sibling
Alpaca tools showed `41 ok`. Latency was non-trivial, so it was fetching — not
failing on a missing key.

**Root cause:** The daily-bar fallback was gated on **base-symbol** sparsity
(`len(base_returns) < _MIN_RETURNS`). The real failure is the opposite case: the
traded symbol is liquid (ample intraday bars) but a **peer** is sparse/illiquid,
so every `_pearson(base, peer)` returns `None` → no correlations → `{}`. Because
the base series looked fine, the daily retry never fired, and the reasoning node
records `success=bool(result)`, so the empty result counted as a hard error on
every call.

**Fix:** `api/services/market_intel.py` — extract `_correlation_map(symbol, peers,
closes)` and trigger the daily fallback on the actual no-result condition
(`if not correlations:`) instead of base-symbol sparsity, so a liquid base with
sparse peers still retries on around-the-clock daily bars.

**Regression test:** `tests/api/test_market_intel.py::test_correlation_falls_back_to_daily_when_only_peers_are_sparse`

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

## `check_cross_asset_correlation` still `{}` outside market hours (after the start-window fix)

**Symptom:** Even with the recent-`start` fix, the correlation tool still showed
`success: false` on a large share of decisions — concentrated outside regular
trading hours.

**Root cause:** It only ever requested **1-minute** bars. Equities have no 1-min
bars outside market hours and intraday crypto bars can be too sparse to yield the
`_MIN_RETURNS` (3) return observations a Pearson correlation needs, so the tool
fell through to `{}`.

**Fix:** `_fetch_bars` is now parametrized by `timeframe` / `limit` / `start_delta`,
and `compute_cross_asset_correlation` falls back to **daily** bars
(`_CORRELATION_DAILY_TIMEFRAME`, 10 bars) when the 1-min series is too short —
a coarser correlation that is available around the clock
(`api/services/market_intel.py`). The single-symbol macro-regime fetch reuses the
same `_fetch_bars` helper.

**Still `{}`?** If correlation (and order-book/news) are empty even with the
fallback, `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` are unset in the environment —
that is the only remaining systemic cause.

**Regression test:** `tests/api/test_market_intel.py::test_correlation_falls_back_to_daily_bars_when_intraday_sparse`

## Macro regime serialized as `"MacroRegime.RISK_ON"` on Python 3.10 (CI-only failure)

**Symptom:** `tests/api/test_market_intel.py::test_macro_regime_*` failed on the
3.10 CI leg (passed on 3.11) with
`assert 'MacroRegime.RISK_ON' == <MacroRegime.RISK_ON: 'risk_on'>` — the regime
payload value carried the enum's class-qualified name instead of `"risk_on"`.

**Root cause:** `fetch_macro_regime` stored the regime as `str(regime)`. On
Python 3.11 `enum.StrEnum` is real (`str()` returns the value), but on 3.10 the
`StrEnum` backport shim in `api/constants.py` is a bare `class StrEnum(str, Enum)`
that does NOT override `__str__`, so `str(MacroRegime.RISK_ON)` falls back to
`Enum.__str__` → `"MacroRegime.RISK_ON"`.

**Fix:** Use `regime.value` instead of `str(regime)` in `api/services/market_intel.py`
— a plain `"risk_on"` string on both interpreter versions, matching the value the
Redis-cached path returns.

**Regression test:** `tests/api/test_market_intel.py::test_macro_regime_risk_on_when_benchmark_trends_up`

## `check_cross_asset_correlation` shows 100% err on the tool-governance panel

**Symptom:** The reasoning tool `check_cross_asset_correlation` reads as
`38× · 0 ok · 100% err` on the Tool Governance panel, while every other
perception tool (order book, news, macro) shows `0% err`. Looks like the tool
is broken even though the Alpaca key works.

**Root cause:** `_gather_market_intel()` recorded tool telemetry with
`success=bool(result)` — so an **empty** result (`{}`) counted as a *failure*.
`compute_cross_asset_correlation` legitimately returns `{}` when there are no
correlatable peer bars this cycle (a data-availability fact, not an exception),
so a perfectly-functioning best-effort tool was mislabeled 100% err. The memory
tools (`get_ic_weights`, `query_similar_trades`) already used the correct
"success == did not raise" convention; the market-intel path was the outlier.

**Fix:** `api/services/agents/reasoning_agent.py::_gather_market_intel` now
records `success = the call completed without raising`. Empty data no longer
inflates the failure rate; a tool's *value* is still captured separately by its
realized-PnL alpha. (The empty-result reality is unchanged — see the daily-bar
fallback note above for why correlation can still be sparse.)

**Regression test:** `tests/agents/test_reasoning_agent.py::test_market_intel_empty_result_records_success_not_error`
