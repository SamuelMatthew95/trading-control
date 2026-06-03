# Data-Consistency Troubleshooting

The same concepts (PnL, positions, win rate, decisions) used to be computed in
several code paths that drifted out of sync. Each entry below is one such
divergence and the single-source-of-truth that now prevents it.

## Win rate differed between dashboard endpoints

**Symptom:** The Overview P&L card and the paired-P&L view showed different win
rates for the same trades; opening positions dragged the rate down.

**Root cause:** Three memory readers divided winners by `len(orders)` (which
includes opening fills with `pnl=None` and zero-PnL scratches) while a fourth
divided by `winning + losing`. Same data, different denominators.

**Fix:** One canonical definition in `api/services/metrics_calc.py`
(`win_rate = winning / (winning + losing)`, opens and scratches excluded).
`dashboard/pnl.py`, `metrics_aggregator._memory_pnl_metrics` /
`_memory_paired_pnl`, and `in_memory_store.paired_pnl_payload` all use it.

**Regression test:** `tests/core/test_metrics_calc.py::test_three_memory_readers_agree_on_win_rate`

## Active-position count disagreed with the positions list

**Symptom:** The dashboard's "active positions" number could differ from the
number of rows in the open-positions table.

**Root cause:** `open_positions()` required `side in {long, short}` while
`normalized_open_positions()` required only `abs(qty) > 0`, so a `qty>0`
position with a missing side counted in one path but not the other.

**Fix:** Canonical rule `abs(qty) > 0` (side-agnostic — a flat position has
qty 0) via `InMemoryStore.get_active_position_count()` /
`has_active_position()`; `open_positions()` uses the same predicate.

**Regression test:** `tests/core/test_active_position_count.py::test_count_equals_list_length_across_all_read_paths`

## InMemoryStore positions drifted from the broker (and reset on restart)

**Symptom:** Dashboard average cost / unrealized PnL disagreed with the broker
after adding to a position, and positions vanished after a redeploy while the
broker still held them.

**Root cause:** Two independent position ledgers. The execution engine wrote
`InMemoryStore.positions` via `apply_signed_delta` (which preserved the first
entry price on adds) while reject/PnL read the PaperBroker (Redis, weighted
average). Redis persists across restarts; the store does not.

**Fix:** The PaperBroker (Redis `paper:positions`) is the single source of
truth. After every in-memory fill the store mirrors the broker's authoritative
position via `InMemoryStore.mirror_broker_position` (the single
`ExecutionEngine._record_fill_to_store` path), and `startup._hydrate_positions_from_broker`
seeds the mirror on boot so a restart no longer blanks the dashboard.

**Regression test:** `tests/agents/test_execution_position_ssot.py::test_store_position_mirrors_broker_after_add`

## Phantom SELLs in the decision feed never produced PnL

**Symptom:** The System page feed showed "SELL AAPL / SELL BTC/USD" but the
dashboard stayed at $0 P&L and 0 positions.

**Root cause:** `ReasoningAgent` published (and recorded to `decisions:recent`)
SELL decisions for symbols with no open position. The `ExecutionEngine`
correctly rejected them (`reject_unmatched_sell`), so they never became orders —
but the advisory feed had already advertised them at decision time.

**Fix:** The agent reads the open-long qty from the PaperBroker (the same source
the engine rejects against) in `_gather_context` and, in `_apply_risk_hierarchy`,
downgrades a SELL for a flat symbol to HOLD tagged
`downgrade_reason=sell_without_open_long`. The feed now only advertises actions
that can execute; the engine reject remains as the backstop. Use
`scripts/diagnose_live_regime.py` to quantify phantom SELLs against live Redis.

**Regression test:** `tests/agents/test_reasoning_position_gate.py::test_sell_with_no_open_long_downgraded_to_hold`
