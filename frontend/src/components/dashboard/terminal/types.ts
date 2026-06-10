/** A single real price sample (epoch ms + price). */
export interface PricePoint {
  t: number
  p: number
}

/** A watchlist row built from real prices + real stream history.
 *  price/changePct are null until live data exists — rendered as '--',
 *  never a fabricated number. */
export interface WatchRow {
  sym: string
  name: string
  price: number | null
  changePct: number | null
  spark: number[]
}

/** Live session stats for the selected symbol's chart header. */
export interface SymbolView {
  sym: string
  name: string
  price: number
  open: number
  high: number
  low: number
  changeAbs: number
  changePct: number
  /** Real L1 best bid/ask (two-sided only); null when no live quote. */
  bid: number | null
  ask: number | null
  points: PricePoint[]
}

/** A normalised open position for the read-only blotter. */
export interface TerminalPosition {
  symbol: string
  side: string
  qty: number
  avg: number
  last: number
  pnl: number
  pnlPct: number
}
