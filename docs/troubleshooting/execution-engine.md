# Execution Engine Troubleshooting

## Normal (Kelly-sized) BUYs had no pre-trade position cap

**Symptom:** A buggy or hallucinated `SIZE_PCT` (Kelly fraction) from `ReasoningAgent` could open an arbitrarily large long position. The pre-trade size caps (`MAX_SYMBOL_EXPOSURE`, `MAX_OPEN_POSITION_QTY`) were enforced only on *fallback* signals; normal Kelly-sized BUYs went to the broker with no upper bound. (SELLs were already bounded by `reject_unmatched_sell` + the oversell clamp.)

**Root cause:** `_apply_kelly_sizing()` returns `SIZE_PCT × portfolio / price` with no clamp, and the normal execution path had no symmetric overbuy guard to match the SELL oversell clamp.

**Fix:** Added `clamp_buy_to_position_limit()` (`api/services/execution/position_math.py`) and applied it in both execution paths (`_process_with_db`, `_process_in_memory`) right after the oversell clamp: a BUY is clamped so the resulting long never exceeds `min(MAX_SYMBOL_EXPOSURE, MAX_OPEN_POSITION_QTY)`; an order already at the cap is rejected (`execution_buy_rejected_position_limit`), and an oversized one is reduced (`execution_buy_qty_clamped_to_position_limit`). Short-covering up to the cap passes through.

**Regression test:** `tests/core/test_position_limit_clamp.py::test_huge_buy_from_flat_is_clamped_to_cap`

## Score parsing — `"n/a"` sends decisions to DLQ

**Symptom:** Hold decisions from `ReasoningAgent` land in the dead-letter queue instead of producing an idle heartbeat.

**Root cause:** `float("n/a")` raises `ValueError`. The engine treated every non-numeric score as fatal.

**Fix:** `_as_score()` in `api/services/execution/decision_utils.py` catches parse errors and returns `None`, falling through to the next score key and ultimately defaulting to `0.5`.

**Regression test:** `tests/agents/test_execution_engine_helpers.py::test_extract_scores_malformed_string_falls_through`

---

## Score parsing — `0.0` confidence promoted to `0.5`

**Symptom:** Trades execute at `signal_confidence = 0.5` even when the decision explicitly set it to `0.0` (the minimum valid score).

**Root cause:** Guard was `if score:` — falsy for Python `float(0.0)`.

**Fix:** `_as_score()` checks `None` and `""` explicitly, so `0.0` and `"0.0"` are preserved.

**Regression test:** `tests/agents/test_execution_engine_helpers.py::test_extract_scores_python_float_zero_stays_zero`

---

## Naked SELL — fake negative P&L on dashboard

**Symptom:** Dashboard shows negative realized P&L from SELL orders that have no matching earlier BUY. Trade feed contains closed-trade rows without corresponding open-position entries.

**Root cause:** The execution engine's `reject_unmatched_sell()` guard stopped an invalid SELL from reaching the broker, but it only logged a warning and returned silently — no rejection event was published and nothing was recorded in the runtime store. Downstream consumers (dashboard P&L, trade feed) had no signal that the SELL was blocked, so any cached state from a previous run could produce phantom negative numbers.

**Fix:** After `reject_unmatched_sell()` returns `True`, the engine now:
1. Publishes a `SELL_REJECTED_NO_OPEN_POSITION` event to `STREAM_SELL_REJECTED` so consumers know the order was blocked.
2. Records the rejection in `InMemoryStore.rejected_sells` (memory-mode path) so the dashboard never counts it as a closed trade.
3. Clamps oversell quantity to the available open position qty instead of creating a naked short position.

Three new `InMemoryStore` methods expose explicit lifecycle checks: `has_open_position(symbol)`, `get_open_position(symbol)`, `reject_sell_no_position(...)`.

**Regression test:** `tests/agents/test_trade_lifecycle_guardrails.py` (full file)

---

## Decisions backlog — high count, zero executions

**Symptom:** Dashboard shows hundreds of decisions with zero corresponding trade executions.

**Check in order:**

1. `GET /system/trading-mode` → `status: KILL_SWITCH` means the kill switch is engaged.
2. `GET /system/trading-mode` → `status: PAUSED` means the circuit breaker is active. Clear it: `POST /system/trading-mode {"status": "TRADING"}`.
3. Agent heartbeat for `ExecutionEngine` shows STALE or OFFLINE — the process is not running.
4. Check `signal_confidence` values in recent decisions. If they are all below the execution gate threshold, signals are being filtered before reaching the broker.

---

## Fallback guard allows position-flip trades when abs exposure decreases

**Symptom:** A fallback buy of qty=7 when short 5 is allowed through, flipping the position from short to long, even though the guard should block position flips.

**Root cause:** `_enforce_fallback_trade_guard` evaluated `reduces_abs_exposure` before the zero-crossing check. A buy of 7 against a short of 5 gives `signed_after = +2`, and `abs(2) <= abs(-5)` is `True`, so `reduces_abs_exposure` was `True` and the trade was passed as reduce-only. The zero-crossing guard (`current < 0 < after`) was in an `elif` that was never reached.

**Fix:** Swapped the check order — position-flip (zero-crossing) is checked first and always blocks. The reduce-only path is only reached when there is no sign change.

**Regression test:** `tests/agents/test_execution_fallback_guard.py::test_fallback_buy_over_closes_short_and_opens_long_blocked`

## Fallback guard silently blocks ALL paper trades when no LLM key is configured

**Symptom:** Dashboard shows zero orders, zero positions, zero P&L, and SYSTEM STATUS: IDLE indefinitely — even with Signal Agent and Execution Engine showing thousands of events.

**Root cause:** Without an LLM API key every reasoning decision has `llm_succeeded=False` and is marked `is_fallback=True`. `_enforce_fallback_trade_guard` then checks `settings.ALLOW_FALLBACK_TRADES` (default `False`) and blocks the trade. `EXECUTION_DECISION_THRESHOLD_MEMORY` (0.30) was deliberately lowered to let paper signals through, but the fallback guard fires before the score gate and silently cancels them all.

**Fix:** `_enforce_fallback_trade_guard` in `api/services/execution/execution_engine.py` now returns `False` immediately when `is_db_available()` is `False` — paper/memory mode has no live capital at risk so the fallback guard is irrelevant.

**Regression test:** `tests/agents/test_execution_fallback_guard.py`

---

## Trade-scorer directional tags — `side` is the CLOSING order side, not position direction

**Symptom:** `tests/agents/test_trade_scorer.py` had three failing tests (`..._for_wins`, `..._for_losses`, `..._marks_clean_execution...`): the scorer emitted the opposite price-action tag (e.g. `reversion_luck` instead of `clean_execution`, or no `adverse_price_move`).

**Root cause:** `STREAM_TRADE_COMPLETED` is published by `fill_publisher.publish_fill_events` **only on `is_round_trip_close`**, and its `FieldName.SIDE` is the *closing* order side — closing a long is `side='sell'`, closing a short is `side='buy'`. `_direction_sign_from_side_event` in `trade_scorer.py` correctly implements this (sell→+1 favorable-when-price-rises, buy→−1 favorable-when-price-falls). Commit `fae9346` flipped the code to this contract and updated two tests, but three older fixtures were left using *open-position* semantics (`buy`=long). They became internally contradictory — e.g. a long closed with `side='sell'` but `exit > entry` (price rose, favorable) yet `pnl < 0` — so no consistent sign convention could satisfy them alongside the corrected tests.

**Fix:** Corrected the three stale fixtures to realistic round-trip long closes (`side='sell'`): `for_wins` keeps the favorable up-move, `for_losses` flips `exit_price` to fall against the long, and `clean` tracks `pnl%` to the move. No production code changed — the scorer already matched the real event contract. Added comments at each fixture documenting the close-order convention.

**Regression test:** `tests/agents/test_trade_scorer.py::test_score_trade_adds_price_action_context_labels_for_wins` (and the `_for_losses` / `_marks_clean_execution_on_profitable_trade` siblings)

---

## Confidence gate vs execution-score gate — MOMENTUM signals silently un-tradeable

**Symptom:** Even after price-change (`pct`) was flowing correctly, only STRONG_MOMENTUM signals (composite 0.80) could ever execute — plain MOMENTUM signals (0.55) never placed an order, so trade volume was far lower than the strategy intended and the learning loop saw almost no fills.

**Root cause:** Two independent gates disagreed. The execution-score gate (`compute_execution_score`) was deliberately tuned (`historical_perf=0.6`) so a MOMENTUM signal scores `0.55*0.50 + 0.55*0.30 + 0.6*0.20 = 0.56 > 0.55` and executes — see `tests/agents/test_momentum_gate.py`. But the separate confidence gate `check_confidence_gate` used `SIGNAL_CONFIDENCE_MIN_GATE = 0.65`, and a MOMENTUM signal's `signal_confidence` is 0.55 < 0.65 — so it was blocked *before* the execution-score gate ever ran. The 0.65 value silently nullified the momentum tuning: no momentum trade could pass both gates.

**Fix:** `api/constants.py` — `SIGNAL_CONFIDENCE_MIN_GATE` lowered `0.65 → 0.50`, just below the MOMENTUM composite tier (0.55) and above LOW/noise (0.30). Now MOMENTUM and STRONG signals clear the confidence gate and are then filtered by the (intended) execution-score, regime, net-EV, and cooling-off gates; LOW signals are still blocked. The two gates now agree.

**Regression test:** `tests/agents/test_momentum_gate.py::test_confidence_gate_consistent_with_execution_score_gate`

---

## Cooling-off gate blocked risk-guardian exits — one loss pinned every other position open

**Symptom:** After a single losing close (e.g. a stop-loss banking −2%), every subsequent order was gated with `execution_gated_cooling_off` for the cooldown window — including RiskGuardian's take-profit, trailing-stop, stale-position, and even further stop-loss closes. Winners gave back their gains and breached losers kept running past −5% exactly when the system had just taken a loss. Surfaced by a full-loop memory-mode smoke (broker → guardian → engine → broker): scan 1's BTC stop-loss executed, then the ETH take-profit and DOGE stale close were blocked and the book stayed long.

**Root cause:** `_check_cooling_off_gate` applied to every order side. The gate exists to throttle revenge *entries* after a loss streak, but a SELL in this long-only book only ever reduces exposure — and all risk closes arrive as SELLs on `STREAM_DECISIONS`, so the entry throttle was silently vetoing the risk layer (`api/services/execution/execution_engine.py`).

**Fix:** `_check_cooling_off_gate` returns early for SELL/short sides — cooling-off now gates BUY entries only. Risk closes execute regardless of recent-outcome streaks; the unmatched-sell guard, oversell clamp, kill switch, and market clock still apply to sells.

**Regression test:** `tests/agents/test_execution_engine.py::test_cooling_off_never_blocks_sell_close` (and `::test_cooling_off_blocks_buy_after_loss_streak` pinning that entries stay gated)

---

## No minimum-order-size enforcement → uncloseable sub-minimum "dust" positions

**Symptom:** An operator saw a BTC position of `0.00016819 BTC` (~$11) frozen at a cost basis (`67079`) far above the live price, and read it as the system showing "fake data." The position was real, but far too small to be a normal lot.

**Root cause:** `SUPPORTED_SYMBOLS` / `get_min_size` were documented in `.claude/rules/memory-trading.md` but **never implemented** — the code enforced no order-size floor. So the book could open a sub-minimum lot, and partial closes (take-profit scaling / trailing / opposite-signal exits) could reduce a position down to a sub-minimum remainder. Entry price is preserved across partial closes, so that remainder carried the original (now stale) basis indefinitely. In paper mode it lingers; on a live Alpaca account a sub-minimum SELL is **rejected**, making such dust genuinely uncloseable — a stale basis frozen forever.

**Fix:** Implemented the contract: `SYMBOL_MIN_SIZE` + `get_min_size()` in `api/constants.py`, and `enforce_min_order_size()` in `api/services/execution/position_math.py`. ExecutionEngine (both DB and memory paths) now (a) rejects a BUY/open below the symbol minimum and (b) rounds a SELL up to a full close when the partial would leave a sub-minimum remainder (never leave dust). A full close of an existing sub-min lot is always permitted. RiskGuardian sweeps any existing sub-min holding via a `dust_below_min` close, which clears legacy dust like the position above.

**Regression test:** `tests/agents/test_position_math.py::TestEnforceMinOrderSize`,
`tests/agents/test_execution_engine.py::test_rejects_buy_below_min_order_size`,
`tests/agents/test_risk_guardian.py::test_memory_mode_flushes_sub_min_dust_position`
