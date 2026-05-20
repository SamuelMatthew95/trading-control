# Frontend Troubleshooting

## Session P&L tile loses negative sign

**Symptom:** When session P&L is negative (e.g. -$20.00), the stats tile in the
Trading page shows `$20.00` instead of `-$20.00`. Color still indicates a loss but
the sign is absent.

**Root cause:** The `formatUSD` helper uses `Math.abs` internally so it always
returns a positive string. The stats tile passed the raw value directly without
adding a sign prefix.

**Fix:** `TradingView.tsx` — stats tile value expression now prepends `-` for
negative P&L: `stats.totalPnl < -0.005 ? '-' + formatUSD(totalPnl) : formatUSD(totalPnl)`.
Positive values intentionally omit `+` to stay visually distinct from the `+$x`
format used in trade-row cells (avoids duplicate-text test ambiguity).

**Regression test:** `frontend/src/test/components/TradeFeed.test.tsx` — component
render suite; the unique sign format prevents `getByText(/\+\$x/)` matching both
the tile and the trade row.

## Win-rate shows 0% when server returns empty summary

**Symptom:** When `/dashboard/performance-trends` returns a zero summary
(`win_rate: 0`, `total_trades: 0`) before any trades are graded, the Win Rate tile
shows `0%` even though `tradeFeed` already contains closed fills with computable PnL.

**Root cause:** The fallback condition only checked `win_rate != null`; a genuine
`0` from an empty summary is not null so the fallback computation was skipped.

**Fix:** `TradingView.tsx` — condition now also requires `total_trades > 0`:
`performanceSummary?.win_rate != null && (performanceSummary?.total_trades ?? 0) > 0`.
When both `win_rate` and `total_trades` are 0, the client computes win rate from
the local `tradeFeed` array instead.

**Regression test:** `frontend/src/test/components/TradeFeed.test.tsx` — verify
win rate shows computed value when summary has zero trades.

## In-memory positions show `unrealized_pnl: 0.0` for active shorts

**Symptom:** In memory-fallback mode, open short positions could appear with
`unrealized_pnl: 0.0` (or stale) even when `last_price` and `avg_cost` clearly
imply non-zero P&L.

**Root cause:** Quantity sign conventions were mixed across memory paths.
Some writers persisted short qty as negative while the in-memory paired-PnL
calculator expected strictly positive qty and treated `qty <= 0` as invalid.
That incorrectly marked valid short rows as stale and excluded their unrealized
P&L from summary totals.

**Fix:** `api/in_memory_store.py` now normalizes open-position magnitude with
`abs(qty)` before applying side-aware formulas:

- long: `(last_price - avg_cost) * qty`
- short: `(avg_cost - last_price) * qty`

Rows are marked stale only when price/cost inputs are missing or malformed, not
because short qty is negative.

**Regression tests:**

- `tests/core/test_in_memory_unrealized_pnl.py::test_unrealized_pnl_long_and_short_and_missing_price`
- `tests/core/test_in_memory_unrealized_pnl.py::test_unrealized_pnl_short_with_negative_qty_uses_absolute_position_size`

**Prevention guidance:** Keep unrealized-PnL math centralized in
`InMemoryStore.paired_pnl_payload()` and avoid re-implementing qty-sign logic in
routes/services. Any new writer that mutates memory positions must preserve
`side` and `qty` consistently and include a memory-mode regression test.
