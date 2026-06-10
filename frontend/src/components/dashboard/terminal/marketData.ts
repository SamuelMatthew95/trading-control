/**
 * Trading-terminal data helpers — REAL data only.
 *
 * Everything the terminal shows is real: prices come from the live price stream
 * (the PricePoller, via the Zustand store), positions/P&L come from the paper
 * broker the agents trade through, and the chart/sparklines render the real
 * price history from the market_events stream.
 *
 * There is no synthetic market data, no fallback prices, and no manual order
 * entry — the autonomous agents place orders, and this screen observes them.
 * A symbol with no live data shows '--', never a fabricated number.
 */

export interface UniverseSymbol {
  sym: string
  name: string
}

/** Exactly the symbols the price poller streams (api/workers/price_poller.py
 *  SYMBOLS): crypto 24/7 + equities during market hours. Never list a symbol
 *  here that has no feed — a row pinned to a made-up constant price is worse
 *  than no row at all. */
export const REAL_UNIVERSE: UniverseSymbol[] = [
  { sym: 'BTC/USD', name: 'Bitcoin' },
  { sym: 'ETH/USD', name: 'Ethereum' },
  { sym: 'SOL/USD', name: 'Solana' },
  { sym: 'AAPL', name: 'Apple Inc.' },
  { sym: 'TSLA', name: 'Tesla Inc.' },
  { sym: 'SPY', name: 'S&P 500 ETF' },
]

export const UNIVERSE_SYMBOLS: string[] = REAL_UNIVERSE.map((u) => u.sym)

const BY_SYMBOL = new Map(REAL_UNIVERSE.map((u) => [u.sym, u]))

export function universeName(sym: string): string {
  return BY_SYMBOL.get(sym)?.name ?? sym
}

/** Live price for a symbol from the store, or null when none has streamed yet. */
export function liveStorePrice(prices: Record<string, unknown> | undefined, sym: string): number | null {
  const row = prices?.[sym] as { price?: unknown } | undefined
  const v = typeof row?.price === 'number' ? row.price : Number(row?.price)
  return Number.isFinite(v) && v > 0 ? v : null
}

/** Real L1 best bid/ask for a symbol, or null unless the quote is two-sided. */
export function liveStoreQuote(
  prices: Record<string, unknown> | undefined,
  sym: string,
): { bid: number; ask: number } | null {
  const row = prices?.[sym] as { bid?: unknown; ask?: unknown } | undefined
  const bid = Number(row?.bid)
  const ask = Number(row?.ask)
  if (Number.isFinite(bid) && bid > 0 && Number.isFinite(ask) && ask > 0) return { bid, ask }
  return null
}

// ── Formatters (numeric display is always tabular mono) ──────────────────────

export function fmtCompact(v: number): string {
  if (!Number.isFinite(v)) return '--'
  return new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(v)
}

export function fmtQty(v: number): string {
  if (!Number.isFinite(v)) return '--'
  return Number(v).toLocaleString('en')
}

/** Tailwind text-colour class for a signed value, via the terminal CSS vars. */
export function signClass(v: number): string {
  if (v > 0) return 'txt-up'
  if (v < 0) return 'txt-down'
  return 'text-slate-500 dark:text-slate-400'
}
