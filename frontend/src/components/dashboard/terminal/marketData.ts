/**
 * Trading-terminal market-data layer.
 *
 * Live prices come from the real price stream (the Zustand store). The order
 * book, time & sales tape, candlestick history and watchlist sparklines are
 * deterministic *visualisations* synthesised here, because the platform exposes
 * no Level-2 / OHLC / print feed. They are seeded per-symbol so they stay
 * stable across renders instead of reshuffling on every tick.
 *
 * Account state (positions, P&L, equity, buying power) is ALWAYS real and is
 * never synthesised in this module.
 */

export interface Candle {
  t: number
  o: number
  h: number
  l: number
  c: number
  v: number
}

export interface BookLevel {
  price: number
  size: number
  cum: number
}

export interface Book {
  bids: BookLevel[]
  asks: BookLevel[]
  maxCum: number
}

export interface TapePrint {
  t: number
  price: number
  size: number
  side: 'buy' | 'sell'
}

export interface UniverseSymbol {
  sym: string
  name: string
  base: number
}

/** The 12 symbols the terminal watches. Base prices are display fallbacks —
 *  a live stream price always overrides them when present. */
export const TERMINAL_UNIVERSE: UniverseSymbol[] = [
  { sym: 'AAPL', name: 'Apple Inc.', base: 227.44 },
  { sym: 'NVDA', name: 'NVIDIA Corp.', base: 135.06 },
  { sym: 'TSLA', name: 'Tesla Inc.', base: 338.31 },
  { sym: 'MSFT', name: 'Microsoft Corp.', base: 440.24 },
  { sym: 'AMZN', name: 'Amazon.com Inc.', base: 209.67 },
  { sym: 'META', name: 'Meta Platforms', base: 607.48 },
  { sym: 'AMD', name: 'Adv. Micro Devices', base: 121.81 },
  { sym: 'GOOGL', name: 'Alphabet Inc.', base: 178.34 },
  { sym: 'JPM', name: 'JPMorgan Chase', base: 248.8 },
  { sym: 'SPY', name: 'SPDR S&P 500', base: 596.57 },
  { sym: 'COIN', name: 'Coinbase Global', base: 301.59 },
  { sym: 'PLTR', name: 'Palantir Tech.', base: 73.44 },
]

const SYMBOL_BY_NAME = new Map(TERMINAL_UNIVERSE.map((u) => [u.sym, u]))

export function universeBasePrice(symbol: string): number {
  return SYMBOL_BY_NAME.get(symbol)?.base ?? 100
}

/** Deterministic PRNG (mulberry32) so synthesised data is stable per seed. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function hashString(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

const ONE_MINUTE_MS = 60_000

/**
 * Synthesise `count` one-minute candles for a symbol, seeded so the shape is
 * stable per symbol. The series is normalised to end exactly at `anchor` (the
 * symbol's reference price), so the live price can drive the forming bar on top
 * without the historical bars drifting between renders.
 */
export function generateCandles(symbol: string, anchor: number, count = 220): Candle[] {
  const rnd = mulberry32(hashString(symbol))
  const out: Candle[] = []
  const now = Date.now()
  let price = anchor * (1 + (rnd() - 0.5) * 0.05)
  for (let i = 0; i < count; i += 1) {
    const o = price
    const drift = (rnd() - 0.5) * 0.006
    const c = o * (1 + drift)
    const h = Math.max(o, c) * (1 + rnd() * 0.0028)
    const l = Math.min(o, c) * (1 - rnd() * 0.0028)
    const v = Math.floor(rnd() * 9000) + 800
    out.push({ t: now - (count - 1 - i) * ONE_MINUTE_MS, o, h, l, c, v })
    price = c
  }
  const last = out[out.length - 1].c
  const scale = last > 0 ? anchor / last : 1
  for (const k of out) {
    k.o *= scale
    k.h *= scale
    k.l *= scale
    k.c *= scale
  }
  return out
}

export interface DayStats {
  open: number
  high: number
  low: number
}

export function dayStats(candles: Candle[]): DayStats {
  if (candles.length === 0) return { open: 0, high: 0, low: 0 }
  let high = -Infinity
  let low = Infinity
  for (const c of candles) {
    high = Math.max(high, c.h)
    low = Math.min(low, c.l)
  }
  return { open: candles[0].o, high, low }
}

/**
 * Synthesise a Level-2 depth ladder around `mid`. `nonce` shifts the seed so
 * sizes shimmer slightly each tick (a live order book is never static) while
 * the price grid stays anchored to the mid.
 */
export function generateBook(symbol: string, mid: number, nonce = 0): Book {
  const rnd = mulberry32(hashString(symbol) + nonce * 2654435761)
  const step = Math.max(0.01, Number((mid * 0.00009).toFixed(2)) || 0.01)
  const bids: BookLevel[] = []
  const asks: BookLevel[] = []
  let cumA = 0
  let cumB = 0
  for (let i = 0; i < 12; i += 1) {
    const sizeA = Math.floor(rnd() * 900) + 60
    cumA += sizeA
    asks.push({ price: mid + step * (i + 1), size: sizeA, cum: cumA })
    const sizeB = Math.floor(rnd() * 900) + 60
    cumB += sizeB
    bids.push({ price: Math.max(0.01, mid - step * (i + 1)), size: sizeB, cum: cumB })
  }
  return { bids, asks, maxCum: Math.max(cumA, cumB, 1) }
}

/** One synthetic tape print near `mid`, side weighted by the latest move. */
export function generatePrint(symbol: string, mid: number, nonce: number): TapePrint {
  const rnd = mulberry32(hashString(symbol) + nonce * 40503)
  const jitter = (rnd() - 0.5) * Math.max(0.02, mid * 0.0006)
  return {
    t: Date.now(),
    price: Math.max(0.01, mid + jitter),
    size: Math.floor(rnd() * 600) + 1,
    side: rnd() > 0.5 ? 'buy' : 'sell',
  }
}

// ── Formatters (terminal-local; numeric display is always tabular mono) ──────

export function fmtCompact(v: number): string {
  if (!Number.isFinite(v)) return '--'
  return new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(v)
}

export function fmtQty(v: number): string {
  if (!Number.isFinite(v)) return '--'
  return Number(v).toLocaleString('en')
}

/** Live price for a symbol, or null when no stream value is present. */
export function liveStorePrice(prices: Record<string, unknown> | undefined, sym: string): number | null {
  const row = prices?.[sym] as { price?: unknown } | undefined
  const v = typeof row?.price === 'number' ? row.price : Number(row?.price)
  return Number.isFinite(v) && v > 0 ? v : null
}

/** Live price if streamed, else the universe base price. */
export function resolvePrice(prices: Record<string, unknown> | undefined, sym: string): number {
  return liveStorePrice(prices, sym) ?? universeBasePrice(sym)
}

/** Tailwind text-colour class for a signed value, via the terminal CSS vars. */
export function signClass(v: number): string {
  if (v > 0) return 'txt-up'
  if (v < 0) return 'txt-down'
  return 'text-slate-400'
}
