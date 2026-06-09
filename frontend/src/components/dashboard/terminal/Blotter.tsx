'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { formatUSD } from '@/lib/formatters'
import { Panel } from './Panel'
import { fmtQty, signClass } from './marketData'
import type { PaperPosition, WorkingOrder } from './types'

const POSITION_COLS = ['Symbol', 'Side', 'Qty', 'Avg', 'Last', 'Mkt Value', 'P&L', 'P&L%', ''] as const
const WORKING_COLS = ['Time', 'Symbol', 'Side', 'Type', 'Qty', 'Limit', 'TIF', 'Status', ''] as const

function Empty({ label }: { label: string }) {
  return <div className="flex h-full items-center justify-center py-10 text-[12px] text-slate-600">{label}</div>
}

/** Tabbed positions / working-orders blotter (col 2, bottom). */
export function Blotter({
  positions,
  orders,
  onFlatten,
  onCancel,
  onSelect,
}: {
  positions: PaperPosition[]
  orders: WorkingOrder[]
  onFlatten: (symbol: string) => void
  onCancel: (id: string) => void
  onSelect: (symbol: string) => void
}) {
  const [tab, setTab] = useState<'positions' | 'orders'>('positions')
  const totalPnl = positions.reduce((s, p) => s + p.pnl, 0)

  return (
    <Panel className="h-full" bodyClass="flex min-h-0 flex-col">
      <header className="flex h-[var(--term-hdr)] shrink-0 items-center justify-between border-b border-slate-800 px-3">
        <div className="flex items-center gap-1">
          {([
            ['positions', `Positions ${positions.length}`],
            ['orders', `Working ${orders.length}`],
          ] as const).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={cn(
                'rounded-md px-2.5 py-1 text-[11px] font-semibold transition-colors',
                tab === id ? 'bg-slate-800 text-slate-100' : 'text-slate-500 hover:text-slate-300',
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {tab === 'positions' && (
          <div className="flex items-center gap-2 font-mono text-[11px] tabular-nums">
            <span className="text-[10px] uppercase tracking-wider text-slate-500">Unrealized</span>
            <span className={cn('font-bold', signClass(totalPnl))}>
              {totalPnl >= 0 ? '+' : '-'}
              {formatUSD(totalPnl)}
            </span>
          </div>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto thin-scroll">
        {tab === 'positions' ? (
          positions.length === 0 ? (
            <Empty label="No open positions" />
          ) : (
            <table className="w-full text-[12px]">
              <thead>
                <tr className="sticky top-0 bg-slate-900 text-[9px] uppercase tracking-wider text-slate-500">
                  {POSITION_COLS.map((h, i) => (
                    <th
                      key={`${h}${i}`}
                      className={cn(
                        'py-2 font-semibold',
                        i === 0 ? 'pl-3 text-left' : i === 8 ? 'pr-3' : 'px-3 text-right',
                        i === 1 && '!text-left',
                      )}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {positions.map((p) => {
                  const up = p.pnl >= 0
                  return (
                    <tr
                      key={p.symbol}
                      onClick={() => onSelect(p.symbol)}
                      className="cursor-pointer font-mono tabular-nums hover:bg-slate-800/40"
                    >
                      <td className="py-1.5 pl-3 text-left font-bold text-slate-100">{p.symbol}</td>
                      <td className="px-3 text-left">
                        <span
                          className={cn(
                            'rounded px-1.5 py-0.5 text-[10px] font-semibold',
                            p.side === 'long' ? 'badge-up' : 'badge-down',
                          )}
                        >
                          {p.side.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-3 text-right text-slate-300">{fmtQty(p.qty)}</td>
                      <td className="px-3 text-right text-slate-400">{p.avg.toFixed(2)}</td>
                      <td className="px-3 text-right text-slate-200">{p.last.toFixed(2)}</td>
                      <td className="px-3 text-right text-slate-300">{formatUSD(p.qty * p.last)}</td>
                      <td className={cn('px-3 text-right font-semibold', up ? 'txt-up' : 'txt-down')}>
                        {up ? '+' : '-'}
                        {formatUSD(p.pnl)}
                      </td>
                      <td className={cn('px-3 text-right', up ? 'txt-up' : 'txt-down')}>
                        {up ? '+' : ''}
                        {p.pnlPct.toFixed(2)}%
                      </td>
                      <td className="py-1.5 pr-3 text-right">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            onFlatten(p.symbol)
                          }}
                          className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400 hover:border-[var(--down)] hover:text-[var(--down)]"
                        >
                          Flatten
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )
        ) : orders.length === 0 ? (
          <Empty label="No working orders" />
        ) : (
          <table className="w-full text-[12px]">
            <thead>
              <tr className="sticky top-0 bg-slate-900 text-[9px] uppercase tracking-wider text-slate-500">
                {WORKING_COLS.map((h, i) => (
                  <th
                    key={`${h}${i}`}
                    className={cn('py-2 font-semibold', i === 0 ? 'pl-3 text-left' : i === 8 ? 'pr-3' : 'px-3 text-left')}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {orders.map((o) => (
                <tr key={o.id} className="font-mono tabular-nums">
                  <td className="py-1.5 pl-3 text-slate-500">
                    {new Date(o.t).toLocaleTimeString('en', { hour12: false })}
                  </td>
                  <td className="px-3 font-bold text-slate-100">{o.symbol}</td>
                  <td className="px-3">
                    <span className={o.side === 'buy' ? 'txt-up' : 'txt-down'}>{o.side.toUpperCase()}</span>
                  </td>
                  <td className="px-3 capitalize text-slate-300">{o.type}</td>
                  <td className="px-3 text-slate-300">{o.qty}</td>
                  <td className="px-3 text-slate-300">{o.type === 'market' ? '--' : o.price.toFixed(2)}</td>
                  <td className="px-3 text-slate-500">{o.tif}</td>
                  <td className="px-3">
                    <span className="flex items-center gap-1 text-[var(--accent)]">
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--accent)]" />
                      working
                    </span>
                  </td>
                  <td className="py-1.5 pr-3 text-right">
                    <button
                      type="button"
                      onClick={() => onCancel(o.id)}
                      className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400 hover:border-[var(--down)] hover:text-[var(--down)]"
                    >
                      Cancel
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Panel>
  )
}
