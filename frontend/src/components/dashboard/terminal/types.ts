/** A single real price sample (epoch ms + price). */
export interface PricePoint {
  t: number
  p: number
}

/** A watchlist row built from real prices + accumulated history. */
export interface WatchRow {
  sym: string
  name: string
  price: number
  changePct: number
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
