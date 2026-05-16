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
