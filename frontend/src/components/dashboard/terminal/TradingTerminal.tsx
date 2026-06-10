'use client'

import { useMemo, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { useLivePositions } from '@/hooks/useLivePositions'
import {
  REAL_UNIVERSE,
  UNIVERSE_SYMBOLS,
  liveStorePrice,
  liveStoreQuote,
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
  const history = usePriceHistory()

  const [symbol, setSymbol] = useState(UNIVERSE_SYMBOLS[0])

  const watchRows = useMemo<WatchRow[]>(
    () =>
      REAL_UNIVERSE.map((u) => {
        const pts = history[u.sym] ?? []
        // Live stream price first, else the newest real history point, else
        // null — a symbol with no data reads '--', never a fabricated price.
        const price = liveStorePrice(prices, u.sym) ?? pts[pts.length - 1]?.p ?? null
        const open = pts[0]?.p
        const changePct =
          price != null && open != null && open > 0 && pts.length > 1
            ? ((price - open) / open) * 100
            : null
        return {
          sym: u.sym,
          name: u.name,
          price,
          changePct,
          spark: pts.map((pt) => pt.p).slice(-32),
        }
      }),
    [history, prices],
  )

  const view = useMemo<SymbolView>(() => {
    const base = history[symbol] ?? []
    const price = liveStorePrice(prices, symbol) ?? base[base.length - 1]?.p ?? 0
    // Append the latest live price as the line's tip so it stays current between
    // the (calm) history refreshes, without rewriting the real history behind it.
    const last = base[base.length - 1]
    const pts =
      price > 0 && (!last || Math.abs(price - last.p) > 1e-9) ? [...base, { t: Date.now(), p: price }] : base
    const open = pts[0]?.p ?? price
    const seriesPrices = pts.map((pt) => pt.p)
    const high = seriesPrices.length > 0 ? Math.max(...seriesPrices) : price
    const low = seriesPrices.length > 0 ? Math.min(...seriesPrices) : price
    const quote = liveStoreQuote(prices, symbol)
    return {
      sym: symbol,
      name: universeName(symbol),
      price,
      open,
      high,
      low,
      changeAbs: price - open,
      changePct: open > 0 ? ((price - open) / open) * 100 : 0,
      bid: quote?.bid ?? null,
      ask: quote?.ask ?? null,
      points: pts,
    }
  }, [history, prices, symbol])

  const symbolIsLive = liveStorePrice(prices, symbol) != null && view.points.length > 1

  return (
    <div className="flex flex-col bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100 lg:h-[calc(100vh-3rem)] lg:overflow-hidden">
      {/* Wrappers use lg:h-full (fill the grid track), never lg:h-auto —
          auto sizes to CONTENT, so a long list grew past its track and
          painted over the panel below it (decisions bleeding through
          Executions). h-full pins each panel to its track so the Panel's
          own overflow-y-auto body scrolls instead. */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 p-2 lg:grid-cols-[220px_1fr_320px] lg:grid-rows-[minmax(0,1fr)_230px]">
        {/* Watchlist — full height on the left */}
        <div className="h-[320px] min-h-0 lg:col-start-1 lg:row-span-2 lg:row-start-1 lg:h-full">
          <Watchlist rows={watchRows} active={symbol} onSelect={setSymbol} />
        </div>

        {/* Chart panel */}
        <section className="flex h-[420px] min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 lg:col-start-2 lg:row-start-1 lg:h-full">
          <SymbolHeader view={view} live={symbolIsLive} />
          <div className="min-h-0 flex-1">
            <PriceChart points={view.points} />
          </div>
        </section>

        {/* Positions blotter — bottom center */}
        <div className="h-[260px] min-h-0 lg:col-start-2 lg:row-start-2 lg:h-full">
          <PositionsPanel positions={positions} onSelect={setSymbol} />
        </div>

        {/* Right stack: agent decisions + executions */}
        <div className="grid min-h-0 gap-2 lg:col-start-3 lg:row-span-2 lg:row-start-1 lg:grid-rows-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="h-[260px] min-h-0 lg:h-full">
            <DecisionsPanel decisions={recentDecisions} />
          </div>
          <div className="h-[260px] min-h-0 lg:h-full">
            <ExecutionsPanel trades={tradeFeed} />
          </div>
        </div>
      </div>
    </div>
  )
}
