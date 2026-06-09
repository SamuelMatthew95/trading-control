import type { Book, Candle, TapePrint } from './marketData'

/** A position in the terminal's manual paper book. Marked to the live price. */
export interface PaperPosition {
  symbol: string
  side: 'long' | 'short'
  qty: number
  avg: number
  last: number
  pnl: number
  pnlPct: number
}

export type OrderSide = 'buy' | 'sell'
export type OrderType = 'market' | 'limit' | 'stop'
export type TimeInForce = 'DAY' | 'GTC' | 'IOC'

/** A resting (working) order awaiting a fill. */
export interface WorkingOrder {
  id: string
  symbol: string
  side: OrderSide
  type: OrderType
  qty: number
  price: number
  tif: TimeInForce
  t: number
}

/** The shape the order ticket submits. */
export interface OrderDraft {
  symbol: string
  side: OrderSide
  type: OrderType
  qty: number
  price: number
  tif: TimeInForce
}

export type ToastKind = 'buy' | 'sell' | 'work' | 'flat' | 'halt'

export interface ToastMessage {
  kind: ToastKind
  text: string
}

/** A watchlist row (real price when streamed, synthetic sparkline). */
export interface WatchRow {
  sym: string
  name: string
  price: number
  changePct: number
  spark: number[]
}

/** Everything the center column needs for the selected symbol. */
export interface SymbolView {
  sym: string
  name: string
  price: number
  dayOpen: number
  dayHigh: number
  dayLow: number
  changeAbs: number
  changePct: number
  candles: Candle[]
  book: Book
  tape: TapePrint[]
}
