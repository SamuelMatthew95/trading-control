/**
 * Trading-terminal data helpers — REAL data only.
 *
 * Everything the terminal shows is real: prices come from the live price stream
 * (the PricePoller, via the Zustand store), positions/P&L come from the paper
 * broker the agents trade through, and the chart/sparklines are built from the
 * real price history accumulated this session (see usePriceHistory).
 *
 * There is no synthetic market data and no manual order entry — the autonomous
 * agents place orders, and this screen observes them.
 */

export interface UniverseSymbol {
  sym: string
  name: string
  /** Display fallback shown only until the first live price streams in. */
  base: number
}

/** The symbols the platform actually monitors (api.constants.VALID_SYMBOLS):
 *  crypto + equities. Order matches the trading universe. */
export const REAL_UNIVERSE: UniverseSymbol[] = [
  { sym: 'BTC/USD', name: 'Bitcoin', base: 67000 },
  { sym: 'ETH/USD', name: 'Ethereum', base: 3500 },
  { sym: 'SOL/USD', name: 'Solana', base: 145 },
  { sym: 'SPY', name: 'S&P 500 ETF', base: 510 },
  { sym: 'AAPL', name: 'Apple Inc.', base: 178 },
  { sym: 'NVDA', name: 'NVIDIA Corp.', base: 875 },
  { sym: 'MSFT', name: 'Microsoft Corp.', base: 430 },
  { sym: 'GOOGL', name: 'Alphabet Inc.', base: 178 },
]

export const UNIVERSE_SYMBOLS: string[] = REAL_UNIVERSE.map((u) => u.sym)

const BY_SYMBOL = new Map(REAL_UNIVERSE.map((u) => [u.sym, u]))

export function universeName(sym: string): string {
  return BY_SYMBOL.get(sym)?.name ?? sym
}

export function universeBasePrice(sym: string): number {
  return BY_SYMBOL.get(sym)?.base ?? 0
}

/** Live price for a symbol from the store, or null when none has streamed yet. */
export function liveStorePrice(prices: Record<string, unknown> | undefined, sym: string): number | null {
  const row = prices?.[sym] as { price?: unknown } | undefined
  const v = typeof row?.price === 'number' ? row.price : Number(row?.price)
  return Number.isFinite(v) && v > 0 ? v : null
}

/** Live price if streamed, else the symbol's display base. */
export function resolvePrice(prices: Record<string, unknown> | undefined, sym: string): number {
  return liveStorePrice(prices, sym) ?? universeBasePrice(sym)
}

/** Previous-poll price for a symbol, used to seed an initial chart segment. */
export function previousStorePrice(prices: Record<string, unknown> | undefined, sym: string): number | null {
  const row = prices?.[sym] as { previousPrice?: unknown } | undefined
  const v = typeof row?.previousPrice === 'number' ? row.previousPrice : Number(row?.previousPrice)
  return Number.isFinite(v) && v > 0 ? v : null
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
