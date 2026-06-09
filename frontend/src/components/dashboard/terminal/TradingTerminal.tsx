'use client'

import { useMemo, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { useLivePositions } from '@/hooks/useLivePositions'
import {
  REAL_UNIVERSE,
  UNIVERSE_SYMBOLS,
  liveStorePrice,
  resolvePrice,
  universeName,
} from './marketData'
import { usePriceHistory } from './usePriceHistory'
import { Watchlist } from './Watchlist'
import { PriceChart } from './PriceChart'
import { SymbolHeader } from './SymbolHeader'
import { PositionsPanel } from './PositionsPanel'
import { DecisionsPanel } from './DecisionsPanel'
import { ExecutionsPanel } from './ExecutionsPanel'
import type { SymbolView, WatchRow } from './types'

/**
 * The trading terminal — the Overview screen. A dense, multi-panel, READ-ONLY
 * equities + crypto desk. Everything is real: prices stream from the platform's
 * price feed, positions/P&L come from the paper broker the agents trade, and the
 * Decisions/Executions panels show the agents' real output. There is no manual
 * order entry — the autonomous agents place orders; this screen observes them.
 */
export function TradingTerminal({
  recentDecisions = [],
}: {
  recentDecisions?: Array<Record<string, unknown>>
}) {
  const prices = useCodexStore((s) => s.prices)
  const tradeFeed = useCodexStore((s) => s.tradeFeed)
  const positions = useLivePositions()
  const history = usePriceHistory(UNIVERSE_SYMBOLS)

  const [symbol, setSymbol] = useState(UNIVERSE_SYMBOLS[0])

  const watchRows = useMemo<WatchRow[]>(
    () =>
      REAL_UNIVERSE.map((u) => {
        const pts = history[u.sym] ?? []
        const price = resolvePrice(prices, u.sym)
        const open = pts[0]?.p ?? price
        return {
          sym: u.sym,
          name: u.name,
          price,
          changePct: open > 0 ? ((price - open) / open) * 100 : 0,
          spark: pts.map((pt) => pt.p).slice(-32),
        }
      }),
    [history, prices],
  )

  const view = useMemo<SymbolView>(() => {
    const pts = history[symbol] ?? []
    const price = resolvePrice(prices, symbol)
    const open = pts[0]?.p ?? price
    const seriesPrices = pts.map((pt) => pt.p)
    const high = seriesPrices.length > 0 ? Math.max(...seriesPrices, price) : price
    const low = seriesPrices.length > 0 ? Math.min(...seriesPrices, price) : price
    return {
      sym: symbol,
      name: universeName(symbol),
      price,
      open,
      high,
      low,
      changeAbs: price - open,
      changePct: open > 0 ? ((price - open) / open) * 100 : 0,
      points: pts,
    }
  }, [history, prices, symbol])

  const symbolIsLive = liveStorePrice(prices, symbol) != null && view.points.length > 1

  return (
    <div className="flex flex-col bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100 lg:h-[calc(100vh-3rem)] lg:overflow-hidden">
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 p-2 lg:grid-cols-[220px_1fr_320px] lg:grid-rows-[1fr_230px]">
        {/* Watchlist — full height on the left */}
        <div className="h-[320px] min-h-0 lg:col-start-1 lg:row-span-2 lg:row-start-1 lg:h-auto">
          <Watchlist rows={watchRows} active={symbol} onSelect={setSymbol} />
        </div>

        {/* Chart panel */}
        <section className="flex h-[420px] min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 lg:col-start-2 lg:row-start-1 lg:h-auto">
          <SymbolHeader view={view} live={symbolIsLive} />
          <div className="min-h-0 flex-1">
            <PriceChart points={view.points} />
          </div>
        </section>

        {/* Positions blotter — bottom center */}
        <div className="h-[260px] min-h-0 lg:col-start-2 lg:row-start-2 lg:h-auto">
          <PositionsPanel positions={positions} onSelect={setSymbol} />
        </div>

        {/* Right stack: agent decisions + executions */}
        <div className="grid min-h-0 gap-2 lg:col-start-3 lg:row-span-2 lg:row-start-1 lg:grid-rows-2">
          <div className="h-[260px] min-h-0 lg:h-auto">
            <DecisionsPanel decisions={recentDecisions} />
          </div>
          <div className="h-[260px] min-h-0 lg:h-auto">
            <ExecutionsPanel trades={tradeFeed} />
          </div>
        </div>
      </div>
    </div>
  )
}
