# Trading Terminal (Overview page)

The Overview page is a read-only, real-data trading terminal: watchlist, live
chart, L1 quote, positions blotter, agent decisions, and executions. The agents
place orders — the terminal observes them. Bugs in this surface and their fixes
live here.

## Watchlist showed symbols the platform never polls

**Symptom:** NVDA / MSFT / GOOGL rows pinned at a constant price with `+0.00%`
forever — they looked fake because they were: nothing ever updates them.

**Root cause:** The terminal's universe was built from `VALID_SYMBOLS` (broker-
side position validation) instead of the price poller's actual feed set
(`api/workers/price_poller.py` `SYMBOLS`), with hardcoded base prices papering
over the missing feed.

**Fix:** `frontend/src/components/dashboard/terminal/marketData.ts` — the
universe is exactly the polled set (BTC/ETH/SOL 24/7 + AAPL/TSLA/SPY during
market hours); fallback prices removed entirely. A symbol with no live data
renders `--`, never a fabricated number.

**Regression test:** `frontend/src/test/components/DashboardView.test.tsx::does not list symbols the price poller never polls`

## Chart rendered flat with repeated time labels

**Symptom:** The selected symbol's chart was a flat line with the same `HH:MM`
label repeated across the time axis; every watchlist row read `+0.00%`.

**Root cause:** Price history was sampled client-side starting at page load, so
for the first minutes only a handful of near-identical points existed — no
movement to draw, and the axis ticks all fell inside the same minute.

**Fix:** `GET /dashboard/price-history`
(`api/services/dashboard/system.py::get_price_history_payload`) reconstructs the
real per-symbol intraday series from the `market_events` Redis stream — the same
polled prices the agents act on — so the chart and sparklines show real movement
immediately. The frontend refreshes it on a calm 8s interval
(`usePriceHistory`) and appends the live tip between refreshes; the time axis is
span-aware (seconds → HH:MM → date).

**Regression test:** `tests/api/test_price_history.py`

## Real L1 bid/ask was fetched and then thrown away

**Symptom:** No bid/ask anywhere on the dashboard even though Alpaca's
latest-quotes responses carry them on every poll.

**Root cause:** `_fetch_crypto` / `_fetch_stocks` parsed `bp`/`ap`, used them to
pick a last price, and discarded them.

**Fix:** The fetchers return full L1 quotes (`{price, bid, ask}`); the REST
price cache (`prices:{symbol}`) carries two-sided bid/ask. The agent stream and
pub/sub payloads are deliberately unchanged, and the momentum anchor
(`_PollerState.last_prices`) stays scalar. The terminal header shows
`BID / ASK / SPR` only when a real two-sided quote exists.

**Regression test:** `tests/core/test_price_poller.py::test_run_poll_cycle_caches_real_bid_ask`

## Header equity drifted from broker truth

**Symptom:** Header Equity / Buying Power were derived from the
localStorage-cached order history (capped at 100 orders), so they drifted from
the broker's actual balance over long sessions and restarts.

**Root cause:** Client-side derivation from partial history instead of reading
the PaperBroker's real cash.

**Fix:** `GET /account` (`api/routes/positions.py::get_account`) returns the
broker's real cash with positions marked to the live price cache; the frontend
(`useTerminalAccount`) uses broker cash + client-side live marks so the number
still ticks between polls, and falls back to the derived value only when the
broker is unreachable (reported as `source: "unavailable"`, shown as nulls —
never fabricated dollars).

**Regression test:** `tests/api/test_account.py`
