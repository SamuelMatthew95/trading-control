'use client'

import { memo, useMemo } from 'react'
import { cn } from '@/lib/utils'

type PositionRecord = Record<string, unknown>

const formatUSD = (value?: number | null): string => {
  if (value == null || Number.isNaN(value) || !Number.isFinite(value)) return '--'
  return `$${Math.abs(value).toFixed(2)}`
}

function toFiniteNumber(value: unknown): number | null {
  const cast = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(cast) ? cast : null
}

export const PositionsTable = memo(function PositionsTable({
  positions,
  onClose,
  onViewDetails,
}: {
  positions: PositionRecord[]
  onClose: (position: PositionRecord) => void
  onViewDetails: (position: PositionRecord) => void
}) {
  const rows = useMemo(
    () =>
      positions.map((position, index) => {
        const pnl = toFiniteNumber(position?.pnl)
        const pnlPct = toFiniteNumber(position?.pnl_percent)
        const isPositive = (pnl ?? 0) >= 0
        const side = String(position?.side ?? '--').toUpperCase()
        return {
          key: `${String(position?.symbol ?? 'UNKNOWN')}-${index}`,
          symbol: String(position?.symbol ?? '--'),
          side,
          qty: String(position?.qty ?? '--'),
          entry: formatUSD(toFiniteNumber(position?.entry_price)),
          current: formatUSD(toFiniteNumber(position?.current_price)),
          pnl: pnl == null ? '--' : `${isPositive ? '+' : '-'}${formatUSD(pnl)}`,
          pnlPct: pnlPct == null ? '--' : `${pnlPct.toFixed(2)}%`,
          isPositive,
          raw: position,
          hasDetails: Boolean(
            (typeof position?.trace_id === 'string' && position.trace_id) ||
            (typeof position?.execution_trace_id === 'string' && position.execution_trace_id) ||
            (typeof position?.signal_trace_id === 'string' && position.signal_trace_id) ||
            (typeof position?.order_id === 'string' && position.order_id)
          ),
        }
      }),
    [positions]
  )

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 sm:p-5">
      <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-400">Open Positions</p>
      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead>
            <tr className="border-b border-slate-800">
              {['Symbol', 'Side', 'Qty', 'Entry', 'Current', 'P&L', 'P&L %', 'Actions'].map((head) => (
                <th key={head} className="px-2 py-2 text-left text-xs font-semibold uppercase tracking-widest text-slate-500">
                  {head}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0
              ? Array.from({ length: 4 }).map((_, index) => (
                  <tr key={`placeholder-${index}`} className="border-t border-slate-800">
                    <td colSpan={8} className="px-2 py-3">
                      <div className="h-6 rounded bg-slate-800/70" />
                    </td>
                  </tr>
                ))
              : rows.map((row) => (
                  <tr key={row.key} className="border-t border-slate-800">
                    <td className="px-2 py-2 text-sm font-mono tabular-nums text-slate-100">{row.symbol}</td>
                    <td className="px-2 py-2">
                      <span className={cn('rounded px-2 py-0.5 text-xs font-semibold', row.side === 'LONG' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-rose-500/15 text-rose-400')}>
                        {row.side}
                      </span>
                    </td>
                    <td className="w-20 px-2 py-2 text-right text-sm font-mono tabular-nums text-slate-100">{row.qty}</td>
                    <td className="w-24 px-2 py-2 text-right text-sm font-mono tabular-nums text-slate-100">{row.entry}</td>
                    <td className="w-24 px-2 py-2 text-right text-sm font-mono tabular-nums text-slate-100">{row.current}</td>
                    <td className={cn('w-24 px-2 py-2 text-right text-sm font-mono tabular-nums font-bold', row.isPositive ? 'text-emerald-400' : 'text-rose-400')}>
                      {row.pnl}
                    </td>
                    <td className={cn('w-20 px-2 py-2 text-right text-xs font-mono tabular-nums', row.isPositive ? 'text-emerald-400' : 'text-rose-400')}>
                      {row.pnlPct}
                    </td>
                    <td className="px-2 py-2 text-right">
                      <div className="flex justify-end gap-2">
                        <button className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] font-semibold text-rose-300 hover:bg-rose-500/20" onClick={() => onClose(row.raw)}>
                          Close Position
                        </button>
                        <button
                          className="rounded border border-slate-600 bg-slate-800 px-2 py-1 text-[11px] font-semibold text-slate-200 hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
                          onClick={() => onViewDetails(row.raw)}
                          disabled={!row.hasDetails}
                        >
                          View Details
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>
      </div>
    </div>
  )
})
