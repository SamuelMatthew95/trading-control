'use client'

import { useMemo } from 'react'
import { TerminalCard, SectionHeader, StateIndicator } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, getNumberTone } from '@/lib/state'
import {
  formatCurrency,
  formatTimestamp,
  parseTimestamp,
  toFiniteNumber,
} from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import { PRICE_LIVE_WINDOW_MS, TICKER_SYMBOLS } from '@/lib/constants/trading'
import type { PriceData } from '@/stores/useCodexStore'
import { PriceTileSkeleton } from './PriceTileSkeleton'

interface LiveMarketPricesProps {
  prices: Record<string, PriceData>
  loading: boolean
}

interface PriceWithTimestamp extends PriceData {
  ts?: string | null
  timestamp?: string | null
}

function getFreshnessTone(prices: Record<string, PriceData>) {
  const ages = Object.values(prices)
    .map((p) => {
      const r = p as PriceWithTimestamp
      return parseTimestamp(r?.updatedAt ?? r?.ts ?? r?.timestamp)
    })
    .filter((d): d is Date => d instanceof Date)
    .map((d) => Date.now() - d.getTime())
  const freshestMs = ages.length > 0 ? Math.min(...ages) : null
  if (freshestMs == null) return { tone: 'muted' as const, label: 'No Data' }
  if (freshestMs <= PRICE_LIVE_WINDOW_MS) return { tone: 'pos' as const, label: 'Live' }
  return { tone: 'warn' as const, label: 'Stale' }
}

export function LiveMarketPrices({ prices, loading }: LiveMarketPricesProps) {
  const tickerEntries = useMemo(
    () => TICKER_SYMBOLS.map((symbol) => [symbol, prices[symbol]] as const),
    [prices],
  )

  const freshness = useMemo(() => {
    if (loading) return { tone: 'warn' as const, label: 'Loading' }
    if (Object.keys(prices).length === 0) return { tone: 'muted' as const, label: 'No Data' }
    return getFreshnessTone(prices)
  }, [loading, prices])

  return (
    <TerminalCard>
      <SectionHeader
        title="Live Market Prices"
        right={<StateIndicator tone={freshness.tone} label={freshness.label} pulse={loading} />}
      />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {loading
          ? Array.from({ length: 6 }).map((_, i) => <PriceTileSkeleton key={`skel-${i}`} />)
          : tickerEntries.map(([symbol, priceData]) => {
              const price = toFiniteNumber(priceData?.price)
              const previous = toFiniteNumber(priceData?.previousPrice)
              const observedChange = toFiniteNumber(priceData?.change)
              const change = observedChange ?? (price != null && previous != null ? price - previous : null)
              const hasData = price != null
              const changeTone = getNumberTone(change)
              return (
                <div
                  key={symbol}
                  className="rounded-[6px] border border-slate-200 p-3 dark:border-slate-800"
                >
                  <div className="flex items-center justify-between">
                    <p className={UI_TEXT.label}>{symbol}</p>
                    <StateIndicator tone={hasData ? 'pos' : 'muted'} />
                  </div>
                  <p className="mt-1 text-lg font-mono tabular-nums text-slate-900 dark:text-slate-100">
                    {formatCurrency(price)}
                  </p>
                  <div className="mt-2 flex items-center justify-between">
                    <p className={cn('text-xs font-mono tabular-nums', TONE_CLASSES[changeTone].text)}>
                      {change == null || !hasData
                        ? '—'
                        : `${change >= 0 ? '▲' : '▼'} ${formatCurrency(Math.abs(change))}`}
                    </p>
                    <p className={UI_TEXT.muted}>{formatTimestamp(priceData?.updatedAt ?? null)}</p>
                  </div>
                </div>
              )
            })}
      </div>
    </TerminalCard>
  )
}
