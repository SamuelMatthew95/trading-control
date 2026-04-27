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

type EquityOrder = Record<string, unknown>

type EquityPoint = {
  timestamp: number
  label: string
  pnl: number
  equity: number
}

const toFinite = (value: unknown): number | null => {
  if (typeof value === 'number') {
    if (Number.isNaN(value) || !Number.isFinite(value)) return null
    return value
  }
  if (typeof value === 'string') {
    const parsed = Number(value.trim())
    if (Number.isNaN(parsed) || !Number.isFinite(parsed)) return null
    return parsed
  }
  return null
}

const parseTimestamp = (value: unknown): number | null => {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value.getTime()
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null
    const asMs = value > 10_000_000_000 ? value : value * 1000
    return Number.isFinite(asMs) ? asMs : null
  }
  if (typeof value !== 'string') return null
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? null : parsed
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
      equity: running,
      label: formatTickTime(timestamp),
    }
  })
}

export const getPaddedDomain = (series: EquityPoint[]): [number, number] => {
  if (series.length === 0) return [-1, 1]
  const values = series.map((point) => point.equity)
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 0)
  const range = max - min
  const padding = Math.max(range * 0.12, 5)
  return [min - padding, max + padding]
}

export function EquityCurve({
  orders,
  isLoading = false,
  hasError = false,
}: {
  orders: EquityOrder[]
  isLoading?: boolean
  hasError?: boolean
}) {
  const series = useMemo(() => buildEquitySeries(orders), [orders])
  const domain = useMemo(() => getPaddedDomain(series), [series])
  const stats = useMemo(() => {
    if (series.length === 0) return null
    const end = series[series.length - 1]?.equity ?? 0
    const change = end
    const percent = null
    const peak = Math.max(...series.map((point) => point.equity))
    const trough = Math.min(...series.map((point) => point.equity))
    const swing = peak - trough
    return { end, change, percent, peak, swing }
  }, [series])

  if (isLoading) {
    return <div className="h-72 animate-pulse rounded-lg border border-slate-200 bg-slate-100/70 dark:border-slate-800 dark:bg-slate-800/40" />
  }

  if (hasError) {
    return <div className="flex h-72 items-center justify-center rounded-lg border border-dashed border-slate-300 text-sm text-slate-400 dark:border-slate-700">Unable to load equity curve</div>
  }

  if (series.length === 0) {
    return <div className="flex h-72 items-center justify-center rounded-lg border border-dashed border-slate-300 text-sm text-slate-400 dark:border-slate-700">No equity data yet</div>
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
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">Cumulative P&amp;L</p>
          <p className={cn('text-xl font-semibold tabular-nums', positive ? 'text-emerald-500' : 'text-rose-500')}>{formatUSD(last)}</p>
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
            <p className="text-xs font-medium tabular-nums text-slate-700 dark:text-slate-200">{formatUSD(stats?.peak ?? 0)}</p>
          </div>
          <div className="col-span-2 rounded-lg border border-slate-200 bg-white/70 px-2 py-1 dark:col-span-1 dark:border-slate-800 dark:bg-slate-900/60">
            <p className="text-[10px] uppercase tracking-wide text-slate-500">Range</p>
            <p className="text-xs font-medium tabular-nums text-slate-700 dark:text-slate-200">
              {formatUSD(stats?.swing ?? 0)}
              {stats?.percent != null && (
                <span className="ml-1 text-slate-500">
                  ({stats.percent >= 0 ? '+' : ''}
                  {stats.percent.toFixed(1)}%)
                </span>
              )}
            </p>
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
              tickFormatter={formatTickTime}
              tick={{ fill: '#64748b', fontSize: 11 }}
              axisLine={{ stroke: '#334155' }}
              tickLine={{ stroke: '#334155' }}
              minTickGap={24}
            />
            <YAxis
              type="number"
              domain={domain}
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
                const index = item?.payload?.timestamp
                const current = series.find((point) => point.timestamp === index)
                const previous = series[series.findIndex((point) => point.timestamp === index) - 1]
                const change = current && previous ? current.equity - previous.equity : current?.equity ?? 0
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
