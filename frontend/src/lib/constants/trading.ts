/**
 * Trading domain constants.
 */

/** Symbols shown on the live market price tiles. */
export const TICKER_SYMBOLS = [
  'BTC/USD',
  'ETH/USD',
  'SOL/USD',
  'AAPL',
  'TSLA',
  'SPY',
] as const

export type TickerSymbol = (typeof TICKER_SYMBOLS)[number]

/** A price tile is "live" if its freshest update is within this window. */
export const PRICE_LIVE_WINDOW_MS = 60_000

/** Maximum number of trade rows rendered in the trade feed table. */
export const TRADE_FEED_MAX_ROWS = 50

/** Maximum number of agent-thought-stream entries surfaced at once. */
export const AGENT_LOG_MAX_ROWS = 10
