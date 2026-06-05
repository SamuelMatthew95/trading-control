'use client'

import { useMemo } from 'react'
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

// Round a range to a "nice" step (1/2/5 × 10ⁿ) so axis ticks land on clean
// numbers. Otherwise a flat-ish curve worth a couple of dollars gets a padded
// domain like [-6.15, 5] and Recharts labels it with junk (-$0.15, -$3.15…).
function niceStep(range: number): number {
  if (!(range > 0)) return 1
  const rough = range / 4
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
  const step = niceStep(max - min)
  const lo = Math.floor(min / step) * step - step
  const hi = Math.ceil(max / step) * step + step
  const ticks: number[] = []
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Number(v.toFixed(6)))
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
  /** Real-time mark-to-market series, used as a fallback when no trade has
   *  closed yet so an open position still renders a curve (see useLiveEquitySeries). */
  liveSeries?: EquityPoint[]
  isLoading?: boolean
  hasError?: boolean
}) {
  const orderSeries = useMemo(() => buildEquitySeries(orders), [orders])
  // Prefer the realized, order-derived curve. When no trade has closed yet, fall
  // back to the live mark-to-market series so an open position shows a real-time
  // curve instead of an empty "No equity data yet" state.
  const series = useMemo(
    () => (orderSeries.length > 0 ? orderSeries : (liveSeries ?? [])),
    [orderSeries, liveSeries],
  )
  const isLiveSeries = orderSeries.length === 0 && (liveSeries?.length ?? 0) > 0
  const { domain, ticks: yTicks } = useMemo(() => getNiceYAxis(series), [series])
  // Show seconds while the curve still spans only a few minutes (otherwise every
  // HH:MM tick is the same minute and reads as "11:25 AM" four times); drop to
  // HH:MM once it covers enough time for the minutes to differ.
  const xTickFormatter = useMemo(() => {
    const spanMs = series.length > 1 ? series[series.length - 1].timestamp - series[0].timestamp : 0
    const showSeconds = spanMs > 0 && spanMs < 5 * 60 * 1000
    return (ts: number) =>
      new Date(ts).toLocaleTimeString(
        [],
        showSeconds
          ? { hour: '2-digit', minute: '2-digit', second: '2-digit' }
          : { hour: '2-digit', minute: '2-digit' },
      )
  }, [series])
  const stats = useMemo(() => {
    if (series.length === 0) return null
    const end = series[series.length - 1]?.equity ?? 0
    const change = end
    const peak = Math.max(...series.map((point) => point.equity))
    const trough = Math.min(...series.map((point) => point.equity))
    const swing = peak - trough
    return { end, change, peak, swing }
  }, [series])

  if (isLoading) {
    return <div className="h-72 animate-pulse rounded-lg border border-slate-200 bg-slate-100/70 dark:border-slate-800 dark:bg-slate-800/40" />
  }

  if (hasError) {
    return <div className="flex h-72 items-center justify-center rounded-lg border border-dashed border-slate-300 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">Unable to load equity curve</div>
  }

  if (series.length === 0) {
    return <div className="flex h-72 items-center justify-center rounded-lg border border-dashed border-slate-300 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">No equity data yet</div>
  }

  const last = stats?.end ?? 0
  const positive = last >= 0
  const strokeColor = positive ? '#10b981' : '#f43f5e'
  const gradientTop = positive ? 'rgba(16,185,129,0.35)' : 'rgba(244,63,94,0.35)'
  const gradientBottom = positive ? 'rgba(16,185,129,0.02)' : 'rgba(244,63,94,0.02)'

  return (
    <div className="rounded-xl border border-slate-200/90 bg-gradient-to-b from-white via-slate-50/60 to-white p-4 shadow-sm dark:border-slate-800 dark:from-slate-950 dark:via-slate-900/60 dark:to-slate-950">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            {isLiveSeries ? 'Live P&L (open position)' : 'Cumulative P&L'}
          </p>
          <p className={cn('text-xl font-semibold tabular-nums', positive ? 'text-emerald-500' : 'text-rose-500')}>{formatUSD(last)}</p>
          {isLiveSeries && (
            <span className="mt-0.5 inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-500">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
              Live · marks to market in real time
            </span>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2 text-right sm:grid-cols-3">
          <div className="rounded-lg border border-slate-200 bg-white/70 px-2 py-1 dark:border-slate-800 dark:bg-slate-900/60">
            <p className="text-[10px] uppercase tracking-wide text-slate-500">Net</p>
            <p className={cn('text-xs font-medium tabular-nums', (stats?.change ?? 0) >= 0 ? 'text-emerald-500' : 'text-rose-500')}>
              {(stats?.change ?? 0) >= 0 ? '+' : ''}
              {formatUSD(stats?.change ?? 0)}
            </p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white/70 px-2 py-1 dark:border-slate-800 dark:bg-slate-900/60">
            <p className="text-[10px] uppercase tracking-wide text-slate-500">Peak</p>
            <p className="text-xs font-medium tabular-nums text-slate-700 dark:text-slate-200">{stats != null ? formatUSD(stats.peak) : '--'}</p>
          </div>
          <div className="col-span-2 rounded-lg border border-slate-200 bg-white/70 px-2 py-1 dark:col-span-1 dark:border-slate-800 dark:bg-slate-900/60">
            <p className="text-[10px] uppercase tracking-wide text-slate-500">Range</p>
            <p className="text-xs font-medium tabular-nums text-slate-700 dark:text-slate-200">{stats != null ? formatUSD(stats.swing) : '--'}</p>
          </div>
        </div>
      </div>

      <div className="h-72 w-full rounded-lg border border-slate-200/70 bg-white/80 p-2 dark:border-slate-800/80 dark:bg-slate-950/40">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={series} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
            <defs>
              <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={gradientTop} />
                <stop offset="95%" stopColor={gradientBottom} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="2 4" stroke="currentColor" className="text-slate-200 dark:text-slate-800" />
            <XAxis
              dataKey="timestamp"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={xTickFormatter}
              tick={{ fill: '#64748b', fontSize: 11 }}
              axisLine={{ stroke: '#334155' }}
              tickLine={{ stroke: '#334155' }}
              minTickGap={48}
            />
            <YAxis
              type="number"
              domain={domain}
              ticks={yTicks}
              tickFormatter={(value) => formatUSD(value)}
              tick={{ fill: '#64748b', fontSize: 11 }}
              axisLine={{ stroke: '#334155' }}
              tickLine={{ stroke: '#334155' }}
              width={86}
            />
            <ReferenceLine y={0} stroke="#64748b" strokeDasharray="4 4" />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 10, boxShadow: '0 10px 25px rgba(2,6,23,0.35)' }}
              labelStyle={{ color: '#cbd5e1', fontSize: 12 }}
              formatter={(value: number, _name, item) => {
                const change = typeof item?.payload?.delta === 'number' ? item.payload.delta : 0
                return [
                  `${formatUSD(value)} (Δ ${change >= 0 ? '+' : ''}${formatUSD(change)})`,
                  'Equity',
                ]
              }}
              labelFormatter={(value) => formatTooltipTime(Number(value))}
            />
            <Area
              type="monotoneX"
              dataKey="equity"
              stroke={strokeColor}
              strokeWidth={2.5}
              fillOpacity={1}
              fill="url(#equityGradient)"
              isAnimationActive={false}
              connectNulls={false}
              dot={series.length < 3 ? { r: 3, strokeWidth: 0, fill: strokeColor } : false}
              activeDot={{ r: 4, strokeWidth: 0, fill: strokeColor }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {series.length < 2 && <p className="mt-2 text-xs text-slate-500">Need more points to render a full trend.</p>}
    </div>
  )
}
