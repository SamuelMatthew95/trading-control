'use client'

import { useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { cn } from '@/lib/utils'
import { toFiniteNum as toFinite, parseTimestampMs as parseTimestamp } from '@/lib/formatters'

type EquityOrder = Record<string, unknown>

export type EquityPoint = {
  timestamp: number
  label: string
  pnl: number
  delta: number
  equity: number
}

// A combined-series point also remembers whether it came from the live
// mark-to-market sampler (so we only break the rendered line across gaps in the
// continuous live tail, never across the legitimately-spaced realized history).
type CombinedPoint = EquityPoint & { live: boolean }

// Render points allow a null equity so Recharts (connectNulls={false}) draws a
// gap instead of a fabricated sloped segment across a live sampling gap.
type RenderPoint = { timestamp: number; equity: number | null; delta: number }

// Robinhood-style ranges. LIVE is the high-resolution recent tail; the rest
// zoom out across the realized history. ALL shows the entire lifetime.
export type EquityRange = 'LIVE' | '1H' | '1D' | '1W' | '1M' | 'ALL'

export const EQUITY_RANGES: EquityRange[] = ['LIVE', '1H', '1D', '1W', '1M', 'ALL']

const MINUTE = 60 * 1000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

export const RANGE_WINDOW_MS: Record<EquityRange, number> = {
  LIVE: 15 * MINUTE,
  '1H': HOUR,
  '1D': DAY,
  '1W': 7 * DAY,
  '1M': 30 * DAY,
  ALL: Number.POSITIVE_INFINITY,
}

// Human-readable label for the secondary header line (Robinhood-style: the
// headline is the current value, this line names the period it's measured over).
const RANGE_LABEL: Record<EquityRange, string> = {
  LIVE: 'live',
  '1H': 'past hour',
  '1D': 'past day',
  '1W': 'past week',
  '1M': 'past month',
  ALL: 'all time',
}

// Break the live line when two consecutive live samples are more than this far
// apart (reload gap, backgrounded tab). 3s is the sampling cadence, so 45s is
// many missed samples — a real discontinuity, not jitter.
const LIVE_GAP_BREAK_MS = 45 * 1000

const getOrderTimestamp = (order: EquityOrder): number | null => {
  return (
    parseTimestamp(order.filled_at) ??
    parseTimestamp(order.created_at) ??
    parseTimestamp(order.timestamp) ??
    parseTimestamp(order.updated_at) ??
    null
  )
}

// Chart-specific formatter: Recharts callbacks always supply a number (never null),
// and axis/tooltip labels must be locale-stable regardless of user system locale.
// Use Intl.NumberFormat('en-US') rather than the shared formatUSD (which uses
// toLocaleString(undefined, ...) and would vary by device locale on a chart axis).
const formatUSD = (value: number): string =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value)

const signedUSD = (value: number): string => `${value >= 0 ? '+' : ''}${formatUSD(value)}`

const formatTickTime = (timestamp: number): string => {
  const date = new Date(timestamp)
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const formatTooltipTime = (timestamp: number): string => {
  const date = new Date(timestamp)
  return date.toLocaleString([], {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export const buildEquitySeries = (orders: EquityOrder[]): EquityPoint[] => {
  const deduped = new Map<number, number>()

  for (const order of orders) {
    const ts = getOrderTimestamp(order)
    const pnl = toFinite(order.pnl)
    if (ts == null || pnl == null) continue
    deduped.set(ts, (deduped.get(ts) ?? 0) + pnl)
  }

  const sorted = Array.from(deduped.entries()).sort((a, b) => a[0] - b[0])
  let running = 0

  return sorted.map(([timestamp, pnl]) => {
    running += pnl
    return {
      timestamp,
      pnl,
      delta: pnl,
      equity: running,
      label: formatTickTime(timestamp),
    }
  })
}

/**
 * Merge the realized order curve (full history, one step per closed trade) with
 * the live mark-to-market tail into a single lifetime equity series.
 *
 * The realized curve is the backbone; live samples newer than the last closed
 * trade are appended on top. Because the live total already includes realized
 * P&L, the seam is continuous: at a close, realized == live total (unrealized
 * ≈ 0), and while a position is open the live tail rises/falls with unrealized.
 * This is the "see everything" series the range tabs slice into.
 */
export const buildCombinedSeries = (
  orders: EquityOrder[],
  liveSeries: EquityPoint[] = [],
): CombinedPoint[] => {
  const realized: CombinedPoint[] = buildEquitySeries(orders).map((p) => ({ ...p, live: false }))
  const lastRealizedTs = realized.length > 0 ? realized[realized.length - 1].timestamp : -Infinity
  const liveTail: CombinedPoint[] = liveSeries
    .filter((p) => p.timestamp > lastRealizedTs)
    .map((p) => ({ ...p, live: true }))
  return [...realized, ...liveTail]
}

/** Slice the lifetime series to a range window relative to `now`. */
export const filterByRange = (
  series: CombinedPoint[],
  range: EquityRange,
  now: number,
): CombinedPoint[] => {
  if (range === 'ALL' || series.length === 0) return series
  const cutoff = now - RANGE_WINDOW_MS[range]
  return series.filter((point) => point.timestamp >= cutoff)
}

export type WindowStats = {
  last: number
  baseline: number
  change: number
  peak: number
  trough: number
  range: number
}

/**
 * Window-relative stats (Robinhood-style): the change is measured from the
 * baseline — the equity just before the visible window — so each range answers
 * "how did P&L move over this period". When the window reaches inception there
 * is no earlier point, so the baseline is 0 (P&L starts at zero before any
 * trade), making the ALL-range change equal the current total P&L.
 */
export const computeWindowStats = (
  full: CombinedPoint[],
  windowed: CombinedPoint[],
): WindowStats | null => {
  if (windowed.length === 0) return null
  const firstTs = windowed[0].timestamp
  let baseline = 0
  for (const point of full) {
    if (point.timestamp < firstTs) baseline = point.equity
    else break
  }
  const equities = windowed.map((point) => point.equity)
  const last = equities[equities.length - 1]
  const peak = Math.max(...equities)
  const trough = Math.min(...equities)
  return { last, baseline, change: last - baseline, peak, trough, range: peak - trough }
}

/**
 * Insert null-equity break points between consecutive *live* samples that are
 * more than {@link LIVE_GAP_BREAK_MS} apart, so a reload/background gap renders
 * as a break rather than a straight diagonal across time that never happened.
 * The realized backbone (legitimately spaced minutes/hours apart) is never
 * broken, nor is the realized→live seam.
 */
export const buildRenderSeries = (windowed: CombinedPoint[]): RenderPoint[] => {
  const out: RenderPoint[] = []
  for (let i = 0; i < windowed.length; i += 1) {
    const point = windowed[i]
    const prev = windowed[i - 1]
    if (
      prev &&
      prev.live &&
      point.live &&
      point.timestamp - prev.timestamp > LIVE_GAP_BREAK_MS
    ) {
      out.push({ timestamp: prev.timestamp + 1, equity: null, delta: 0 })
    }
    out.push({ timestamp: point.timestamp, equity: point.equity, delta: point.delta })
  }
  return out
}

// Round a range to a "nice" step (1/2/5 × 10ⁿ) so axis ticks land on clean
// numbers. Otherwise a flat-ish curve worth a couple of dollars gets a padded
// domain like [-6.15, 5] and Recharts labels it with junk (-$0.15, -$3.15…).
function niceStep(range: number): number {
  if (!(range > 0)) return 1
  // Target ~3 divisions (plus one step of headroom each side ≈ 4–5 gridlines) so
  // the axis stays clean instead of stacking 8–9 cramped dollar labels.
  const rough = range / 3
  const mag = 10 ** Math.floor(Math.log10(rough))
  const norm = rough / mag
  const niceNorm = norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10
  return niceNorm * mag
}

// Y-axis domain + explicit ticks, snapped to a nice step, always spanning the
// $0 baseline with one step of headroom each side so the line is never glued to
// an edge and every gridline reads as a clean dollar amount.
export const getNiceYAxis = (series: EquityPoint[]): { domain: [number, number]; ticks: number[] } => {
  if (series.length === 0) return { domain: [-1, 1], ticks: [-1, 0, 1] }
  const values = series.map((point) => point.equity)
  let min = Math.min(...values, 0)
  let max = Math.max(...values, 0)
  if (min === max) {
    min -= 1
    max += 1
  }
  const step = Math.max(niceStep(max - min), 0.01)
  const lo = Math.floor(min / step) * step - step
  const hi = Math.ceil(max / step) * step + step
  const ticks: number[] = []
  // `+ 0` normalizes a -0 (or a sub-µ tick that toFixed renders as "-0.000000")
  // to +0, so the axis never shows a spurious "-$0.00" label. The $0.01 step
  // floor above keeps sub-cent P&L from collapsing every tick to 0.
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Number(v.toFixed(6)) + 0)
  return { domain: [lo, hi], ticks }
}

export const getPaddedDomain = (series: EquityPoint[]): [number, number] => getNiceYAxis(series).domain

export function EquityCurve({
  orders,
  liveSeries,
  isLoading = false,
  hasError = false,
}: {
  orders: EquityOrder[]
  /** Real-time mark-to-market series; forms the live tail of the lifetime curve
   *  and the sole source before any trade has closed (see useLiveEquitySeries). */
  liveSeries?: EquityPoint[]
  isLoading?: boolean
  hasError?: boolean
}) {
  const [range, setRange] = useState<EquityRange>('ALL')

  const orderSeries = useMemo(() => buildEquitySeries(orders), [orders])
  // One lifetime series: realized history + live mark-to-market tail.
  const combined = useMemo(
    () => buildCombinedSeries(orders, liveSeries ?? []),
    [orders, liveSeries],
  )
  const hasRealized = orderSeries.length > 0
  // Pure-live mode: an open position with no closed trades yet.
  const isLiveSeries = !hasRealized && combined.length > 0

  // `now` advances every time the series changes (a new live sample arrives every
  // 3s), keeping the relative range windows fresh without a separate timer.
  const now = useMemo(
    () => (combined.length > 0 ? Math.max(Date.now(), combined[combined.length - 1].timestamp) : Date.now()),
    [combined],
  )

  // Disable ranges longer than the available history so the tabs aren't all
  // identical at cold start. LIVE and ALL are always selectable.
  const fullSpanMs = combined.length > 1 ? combined[combined.length - 1].timestamp - combined[0].timestamp : 0
  const isRangeDisabled = (key: EquityRange): boolean =>
    key !== 'ALL' && key !== 'LIVE' && RANGE_WINDOW_MS[key] > fullSpanMs && fullSpanMs > 0

  const effectiveRange = isRangeDisabled(range) ? 'ALL' : range
  const windowed = useMemo(
    () => filterByRange(combined, effectiveRange, now),
    [combined, effectiveRange, now],
  )

  const stats = useMemo(() => computeWindowStats(combined, windowed), [combined, windowed])
  const renderData = useMemo(() => buildRenderSeries(windowed), [windowed])
  const { domain, ticks: yTicks } = useMemo(() => getNiceYAxis(windowed), [windowed])

  // Seconds while the visible window spans only a few minutes, HH:MM up to a
  // day, and a date label once it covers multiple days — so ticks never repeat.
  const xTickFormatter = useMemo(() => {
    const spanMs =
      windowed.length > 1 ? windowed[windowed.length - 1].timestamp - windowed[0].timestamp : 0
    if (spanMs > 0 && spanMs < 5 * MINUTE) {
      return (ts: number) =>
        new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    }
    if (spanMs < DAY) {
      return (ts: number) => new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
    return (ts: number) => new Date(ts).toLocaleDateString([], { month: 'short', day: '2-digit' })
  }, [windowed])

  if (isLoading) {
    return <div className="h-72 animate-pulse rounded-lg border border-slate-200 bg-slate-100/70 dark:border-slate-800 dark:bg-slate-800/40" />
  }

  if (hasError) {
    return <div className="flex h-72 items-center justify-center rounded-lg border border-dashed border-slate-300 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">Unable to load equity curve</div>
  }

  if (combined.length === 0) {
    return <div className="flex h-72 items-center justify-center rounded-lg border border-dashed border-slate-300 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">No equity data yet</div>
  }

  const last = stats?.last ?? 0
  const change = stats?.change ?? 0
  const peak = stats?.peak ?? 0
  const trough = stats?.trough ?? 0
  const swing = stats?.range ?? 0
  // Robinhood colours the curve by the move over the selected period, not by the
  // absolute sign — green when the window is up, red when it's down.
  const positive = change >= 0
  const strokeColor = positive ? '#10b981' : '#f43f5e'
  const fillColor = positive ? 'rgba(16,185,129,0.18)' : 'rgba(244,63,94,0.18)'
  const valueClass = positive ? 'text-emerald-500' : 'text-rose-500'

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            {isLiveSeries ? 'Live P&L (open position)' : 'Cumulative P&L'}
          </p>
          <p className={cn('mt-0.5 text-3xl font-semibold tabular-nums', valueClass)}>{formatUSD(last)}</p>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] font-medium uppercase tracking-wide">
            <span className={cn('inline-flex items-center gap-1', valueClass)}>
              <span aria-hidden>{positive ? '▲' : '▼'}</span>
              {RANGE_LABEL[effectiveRange]}
            </span>
            {isLiveSeries && (
              <span className="inline-flex items-center gap-1 text-emerald-500">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                Live · marks to market in real time
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-x-5 gap-y-1 text-[11px] tabular-nums">
          <span className="inline-flex items-center gap-1.5">
            <span className="uppercase tracking-wide text-slate-500">Net</span>
            <span className={cn('font-medium', valueClass)}>{signedUSD(change)}</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="uppercase tracking-wide text-slate-500">Peak</span>
            <span className="font-medium text-slate-600 dark:text-slate-300">{stats != null ? formatUSD(peak) : '--'}</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="uppercase tracking-wide text-slate-500">Low</span>
            <span className="font-medium text-slate-600 dark:text-slate-300">{stats != null ? formatUSD(trough) : '--'}</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="uppercase tracking-wide text-slate-500">Range</span>
            <span className="font-medium text-slate-600 dark:text-slate-300">{stats != null ? formatUSD(swing) : '--'}</span>
          </span>
        </div>
      </div>

      <div className="mb-3 inline-flex items-center gap-0.5 rounded-lg bg-slate-100/70 p-0.5 dark:bg-slate-900/70">
        {EQUITY_RANGES.map((key) => {
          const disabled = isRangeDisabled(key)
          const active = key === effectiveRange
          return (
            <button
              key={key}
              type="button"
              disabled={disabled}
              onClick={() => setRange(key)}
              aria-pressed={active}
              className={cn(
                'rounded-md px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide transition-colors',
                active
                  ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white'
                  : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200',
                disabled && 'cursor-not-allowed opacity-30 hover:text-slate-500',
              )}
            >
              {key}
            </button>
          )
        })}
      </div>

      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={renderData} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={fillColor} />
                <stop offset="100%" stopColor={fillColor} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} strokeDasharray="3 6" stroke="currentColor" className="text-slate-200/70 dark:text-slate-800/70" />
            <XAxis
              dataKey="timestamp"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={xTickFormatter}
              tick={{ fill: '#94a3b8', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              minTickGap={56}
            />
            <YAxis
              type="number"
              domain={domain}
              ticks={yTicks}
              tickFormatter={(value) => formatUSD(value)}
              tick={{ fill: '#94a3b8', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={64}
            />
            <ReferenceLine y={0} stroke="#64748b" strokeDasharray="4 4" strokeOpacity={0.6} />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 10, boxShadow: '0 10px 25px rgba(2,6,23,0.35)' }}
              labelStyle={{ color: '#cbd5e1', fontSize: 12 }}
              formatter={(value: number, _name, item) => {
                const delta = typeof item?.payload?.delta === 'number' ? item.payload.delta : 0
                return [`${formatUSD(value)} (Δ ${signedUSD(delta)})`, 'Equity']
              }}
              labelFormatter={(value) => formatTooltipTime(Number(value))}
            />
            <Area
              type="monotoneX"
              dataKey="equity"
              stroke={strokeColor}
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#equityGradient)"
              isAnimationActive={false}
              connectNulls={false}
              dot={renderData.length < 3 ? { r: 3, strokeWidth: 0, fill: strokeColor } : false}
              activeDot={{ r: 4, strokeWidth: 0, fill: strokeColor }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {windowed.length < 2 && <p className="mt-2 text-xs text-slate-500">Need more points to render a full trend.</p>}
    </div>
  )
}
