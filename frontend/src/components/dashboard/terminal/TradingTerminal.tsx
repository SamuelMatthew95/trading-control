'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { useLivePositions } from '@/hooks/useLivePositions'
import { cn } from '@/lib/utils'
import {
  dayStats,
  generateBook,
  generateCandles,
  generatePrint,
  hashString,
  liveStorePrice,
  universeBasePrice,
  TERMINAL_UNIVERSE,
  type Candle,
  type TapePrint,
} from './marketData'
import { Watchlist } from './Watchlist'
import { OrderBook } from './OrderBook'
import { Tape } from './Tape'
import { OrderTicket } from './OrderTicket'
import { Blotter } from './Blotter'
import { CandleChart } from './CandleChart'
import { SymbolHeader, type Timeframe } from './SymbolHeader'
import { TerminalToast } from './TerminalToast'
import { deskAccount, usePaperDesk } from './usePaperDesk'
import type { OrderDraft, SymbolView, ToastMessage, WatchRow } from './types'

const LOOP_MS = 900
const TAPE_CAP = 60

/**
 * The trading terminal — the Overview screen. A dense, dark, multi-panel
 * equities desk wired to the real price stream and the shared paper desk.
 * Candles, the L2 book, the tape and sparklines are synthesised visualisations
 * (no such feed exists); account state is the real paper desk.
 */
export function TradingTerminal() {
  const prices = useCodexStore((s) => s.prices)
  const killSwitchActive = useCodexStore((s) => s.killSwitchActive)
  const realPositions = useLivePositions()

  const desk = usePaperDesk()
  const { positions: deskPositions, orders, cash, seed, markToMarket, fillWorking, submit, flatten, cancel } = desk

  const [symbol, setSymbol] = useState('AAPL')
  const [timeframe, setTimeframe] = useState<Timeframe>('1m')
  const [prefillPrice, setPrefillPrice] = useState<number | null>(null)
  const [toast, setToast] = useState<ToastMessage | null>(null)
  const [tick, setTick] = useState(0)

  // Stable per-symbol candle history + accumulating tape (refs so they neither
  // regenerate every render nor reset the live loop).
  const candlesRef = useRef<Record<string, Candle[]>>({})
  const tapeRef = useRef<Record<string, TapePrint[]>>({})

  const candlesFor = useCallback((sym: string): Candle[] => {
    if (!candlesRef.current[sym]) candlesRef.current[sym] = generateCandles(sym, universeBasePrice(sym))
    return candlesRef.current[sym]
  }, [])

  // Price resolver: real stream price when present, else a gently oscillating
  // synthetic price so symbols without a live feed still breathe.
  const priceFor = useCallback(
    (sym: string): number => {
      const live = liveStorePrice(prices, sym)
      if (live != null) return live
      const base = universeBasePrice(sym)
      return base * (1 + Math.sin(tick / 5 + (hashString(sym) % 360)) * 0.0009)
    },
    [prices, tick],
  )
  const priceForRef = useRef(priceFor)
  priceForRef.current = priceFor
  const symbolRef = useRef(symbol)
  symbolRef.current = symbol
  const killedRef = useRef(killSwitchActive)
  killedRef.current = killSwitchActive

  // Seed the paper desk once from the real open positions (or a demo book).
  useEffect(() => {
    seed(realPositions, priceForRef.current)
  }, [seed, realPositions])

  // Seed the tape for a freshly selected symbol so it is never empty.
  useEffect(() => {
    if (!tapeRef.current[symbol]) {
      const mid = priceForRef.current(symbol)
      tapeRef.current[symbol] = Array.from({ length: 24 }, (_, i) => generatePrint(symbol, mid, i + 1))
    }
  }, [symbol])

  // Live loop: advance liveness, mark to market, fill working orders, print tape.
  useEffect(() => {
    const id = setInterval(() => {
      setTick((t) => t + 1)
      const resolve = priceForRef.current
      if (!killedRef.current) {
        markToMarket(resolve)
        const fills = fillWorking(resolve)
        if (fills.length > 0) setToast(fills[fills.length - 1])
      }
      const sym = symbolRef.current
      const arr = tapeRef.current[sym] ?? (tapeRef.current[sym] = [])
      arr.unshift(generatePrint(sym, resolve(sym), Date.now()))
      if (arr.length > TAPE_CAP) arr.pop()
    }, LOOP_MS)
    return () => clearInterval(id)
  }, [markToMarket, fillWorking])

  // Auto-dismiss the toast.
  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(null), 2600)
    return () => clearTimeout(id)
  }, [toast])

  const watchRows = useMemo<WatchRow[]>(
    () =>
      TERMINAL_UNIVERSE.map((u) => {
        const candles = candlesFor(u.sym)
        const open = candles[0]?.o ?? u.base
        const price = priceFor(u.sym)
        return {
          sym: u.sym,
          name: u.name,
          price,
          changePct: open !== 0 ? ((price - open) / open) * 100 : 0,
          spark: candles.slice(-32).map((c) => c.c),
        }
      }),
    // tick drives liveness; priceFor already closes over prices+tick.
    [candlesFor, priceFor],
  )

  const view = useMemo<SymbolView>(() => {
    const meta = TERMINAL_UNIVERSE.find((u) => u.sym === symbol) ?? TERMINAL_UNIVERSE[0]
    const candles = candlesFor(symbol)
    const stats = dayStats(candles)
    const price = priceFor(symbol)
    return {
      sym: meta.sym,
      name: meta.name,
      price,
      dayOpen: stats.open,
      dayHigh: Math.max(stats.high, price),
      dayLow: Math.min(stats.low, price),
      changeAbs: price - stats.open,
      changePct: stats.open !== 0 ? ((price - stats.open) / stats.open) * 100 : 0,
      candles,
      book: generateBook(symbol, price, tick),
      tape: tapeRef.current[symbol] ?? [],
    }
  }, [symbol, candlesFor, priceFor, tick])

  const buyingPower = deskAccount(cash, deskPositions).buyingPower

  const handleSubmit = useCallback(
    (draft: OrderDraft) => {
      if (killedRef.current) {
        setToast({ kind: 'halt', text: 'Kill switch active — order rejected' })
        return
      }
      setToast(submit(draft))
    },
    [submit],
  )

  const handleFlatten = useCallback(
    (sym: string) => {
      setToast(flatten(sym, priceForRef.current(sym)))
    },
    [flatten],
  )

  return (
    <div className="flex flex-col bg-slate-950 text-slate-100 lg:h-[calc(100vh-3rem)] lg:overflow-hidden">
      <div
        className={cn(
          'grid min-h-0 flex-1 gap-2 p-2',
          'grid-cols-1 lg:grid-cols-[220px_1fr_304px] lg:grid-rows-[1fr_230px]',
        )}
      >
        {/* Watchlist — full height on the left */}
        <div className="h-[320px] min-h-0 lg:col-start-1 lg:row-span-2 lg:row-start-1 lg:h-auto">
          <Watchlist rows={watchRows} active={symbol} onSelect={setSymbol} />
        </div>

        {/* Chart panel */}
        <section className="flex h-[420px] min-h-0 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-900 lg:col-start-2 lg:row-start-1 lg:h-auto">
          <SymbolHeader view={view} timeframe={timeframe} setTimeframe={setTimeframe} />
          <div className="min-h-0 flex-1">
            <CandleChart candles={view.candles} lastPrice={view.price} timeframe={timeframe} />
          </div>
        </section>

        {/* Right stack: ticket + (book + tape) */}
        <div className="grid min-h-0 gap-2 lg:col-start-3 lg:row-span-2 lg:row-start-1 lg:grid-rows-[auto_1fr]">
          <OrderTicket
            symbol={symbol}
            price={view.price}
            buyingPower={buyingPower}
            onSubmit={handleSubmit}
            prefillPrice={prefillPrice}
          />
          <div className="grid min-h-0 gap-2 sm:grid-cols-2">
            <OrderBook
              book={view.book}
              mid={view.price}
              onPick={(px) => setPrefillPrice(px + Math.random() * 0.0001)}
            />
            <Tape tape={view.tape} />
          </div>
        </div>

        {/* Blotter — bottom center */}
        <div className="h-[260px] min-h-0 lg:col-start-2 lg:row-start-2 lg:h-auto">
          <Blotter
            positions={deskPositions}
            orders={orders}
            onFlatten={handleFlatten}
            onCancel={cancel}
            onSelect={setSymbol}
          />
        </div>
      </div>

      {toast && <TerminalToast toast={toast} />}
    </div>
  )
}
