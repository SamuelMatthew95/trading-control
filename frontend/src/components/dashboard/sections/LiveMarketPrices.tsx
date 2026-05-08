'use client'

import { useMemo } from 'react'
import { TerminalCard, SectionHeader, StateIndicator } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, getNumberTone, type Tone } from '@/lib/state'
import {
  formatCurrency,
  formatTimestamp,
  parseTimestamp,
  toFiniteNumber,
} from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import { PRICE_LIVE_WINDOW_MS, TICKER_SYMBOLS, type TickerSymbol } from '@/lib/constants/trading'
import {
  INNER_TILE,
  PRICE_TILE_GRID,
  PRIMARY_TEXT,
  ROW_BETWEEN,
} from '@/lib/styles'
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

interface FreshnessSummary {
  tone: Tone
  label: string
}

const SKELETON_KEYS = ['s0', 's1', 's2', 's3', 's4', 's5'] as const

const PRICE_VALUE_TEXT = 'mt-1 text-lg font-mono tabular-nums'
const PRICE_CHANGE_TEXT = 'text-xs font-mono tabular-nums'
const PRICE_FOOTER = 'mt-2 ' + ROW_BETWEEN

function readPriceTimestamp(priceData: PriceData | undefined | null): Date | null {
  if (!priceData) return null
  const r = priceData as PriceWithTimestamp
  return parseTimestamp(r.updatedAt ?? r.ts ?? r.timestamp)
}

function freshnessFromPrices(prices: Record<string, PriceData>): FreshnessSummary {
  const ages: number[] = []
  for (const priceData of Object.values(prices)) {
    const ts = readPriceTimestamp(priceData)
    if (ts) ages.push(Date.now() - ts.getTime())
  }
  if (ages.length === 0) return { tone: 'muted', label: 'No Data' }
  const freshestMs = Math.min(...ages)
  if (freshestMs <= PRICE_LIVE_WINDOW_MS) return { tone: 'pos', label: 'Live' }
  return { tone: 'warn', label: 'Stale' }
}

function resolveFreshness(
  prices: Record<string, PriceData>,
  loading: boolean,
): FreshnessSummary {
  if (loading) return { tone: 'warn', label: 'Loading' }
  if (Object.keys(prices).length === 0) return { tone: 'muted', label: 'No Data' }
  return freshnessFromPrices(prices)
}

function deriveChange(priceData: PriceData | undefined | null): number | null {
  const price = toFiniteNumber(priceData?.price)
  const previous = toFiniteNumber(priceData?.previousPrice)
  const observed = toFiniteNumber(priceData?.change)
  if (observed != null) return observed
  if (price != null && previous != null) return price - previous
  return null
}

function buildSkeletonRow() {
  return SKELETON_KEYS.map((key) => <PriceTileSkeleton key={key} />)
}

function PriceTile(props: { symbol: TickerSymbol; priceData: PriceData | undefined }) {
  const { symbol, priceData } = props
  const price = toFiniteNumber(priceData?.price)
  const change = deriveChange(priceData)
  const hasData = price != null
  const changeTone = getNumberTone(change)
  const changeText =
    change == null || !hasData
      ? '—'
      : `${change >= 0 ? '▲' : '▼'} ${formatCurrency(Math.abs(change))}`

  return (
    <div className={INNER_TILE}>
      <div className={ROW_BETWEEN}>
        <p className={UI_TEXT.label}>{symbol}</p>
        <StateIndicator tone={hasData ? 'pos' : 'muted'} />
      </div>
      <p className={cn(PRICE_VALUE_TEXT, PRIMARY_TEXT)}>{formatCurrency(price)}</p>
      <div className={PRICE_FOOTER}>
        <p className={cn(PRICE_CHANGE_TEXT, TONE_CLASSES[changeTone].text)}>{changeText}</p>
        <p className={UI_TEXT.muted}>{formatTimestamp(priceData?.updatedAt ?? null)}</p>
      </div>
    </div>
  )
}

export function LiveMarketPrices(props: LiveMarketPricesProps) {
  const { prices, loading } = props

  const tickerEntries = useMemo<ReadonlyArray<readonly [TickerSymbol, PriceData | undefined]>>(
    () => TICKER_SYMBOLS.map((symbol) => [symbol, prices[symbol]] as const),
    [prices],
  )

  const freshness = useMemo(() => resolveFreshness(prices, loading), [loading, prices])

  return (
    <TerminalCard>
      <SectionHeader
        title="Live Market Prices"
        right={<StateIndicator tone={freshness.tone} label={freshness.label} pulse={loading} />}
      />
      <div className={PRICE_TILE_GRID}>
        {loading
          ? buildSkeletonRow()
          : tickerEntries.map(([symbol, priceData]) => (
              <PriceTile key={symbol} symbol={symbol} priceData={priceData} />
            ))}
      </div>
    </TerminalCard>
  )
}
