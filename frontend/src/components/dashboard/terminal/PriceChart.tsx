'use client'

import { useMemo } from 'react'
import { Area, AreaChart, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import type { PricePoint } from './types'

const UP = '#10b981'
const DOWN = '#f43f5e'

/**
 * Real intraday price chart for the selected symbol, drawn from the live price
 * history accumulated this session. Theme-aware (recharts colours read fine on
 * both light and dark). No synthetic candles — just the real price line.
 */
export function PriceChart({ points }: { points: PricePoint[] }) {
  const data = useMemo(() => points.map((pt) => ({ t: pt.t, p: pt.p })), [points])

  const positive = data.length > 1 ? data[data.length - 1].p >= data[0].p : true
  const stroke = positive ? UP : DOWN

  const domain = useMemo<[number, number]>(() => {
    if (data.length === 0) return [0, 1]
    const values = data.map((d) => d.p)
    const min = Math.min(...values)
    const max = Math.max(...values)
    const pad = Math.max((max - min) * 0.12, max * 0.0005, 0.01)
    return [min - pad, max + pad]
  }, [data])

  if (data.length < 2) {
    return (
      <div className="flex h-full items-center justify-center text-[11px] font-mono text-slate-500 dark:text-slate-500">
        Accumulating live price history…
      </div>
    )
  }

  return (
    <div className="h-full w-full p-1">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 10, right: 12, left: 12, bottom: 4 }}>
          <defs>
            <linearGradient id="terminalPriceFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity={0.22} />
              <stop offset="100%" stopColor={stroke} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="t"
            type="number"
            domain={['dataMin', 'dataMax']}
            tickFormatter={(t: number) => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            tick={{ fill: '#94a3b8', fontSize: 10, fontFamily: 'var(--font-mono)' }}
            axisLine={false}
            tickLine={false}
            minTickGap={56}
          />
          <YAxis
            orientation="right"
            type="number"
            domain={domain}
            width={56}
            tickFormatter={(v: number) => `$${v.toFixed(2)}`}
            tick={{ fill: '#94a3b8', fontSize: 10, fontFamily: 'var(--font-mono)' }}
            axisLine={false}
            tickLine={false}
          />
          <Area
            type="monotone"
            dataKey="p"
            stroke={stroke}
            strokeWidth={2}
            fill="url(#terminalPriceFill)"
            isAnimationActive={false}
            dot={false}
            activeDot={{ r: 3, strokeWidth: 0, fill: stroke }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
