'use client'

import { useMemo } from 'react'

import { useCodexStore } from '@/stores/useCodexStore'
import { useLivePositions } from '@/hooks/useLivePositions'
import { sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import {
  formatQuantity,
  formatUSD,
  getField,
  getStr,
  positionCostBasis,
  positionQty,
  toFiniteNum as toNum,
} from '@/lib/formatters'
import { positionSideBadgeClass } from '@/lib/dashboard-helpers'
import { cn } from '@/lib/utils'

/**
 * Position drill-in — "click → view → learn" for one symbol. Reads the live
 * position plus that symbol's recent fills/closed trades straight from the store
 * (no new endpoint), so it works identically in DB and memory mode.
 */
export function PositionDetailModal({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  const positions = useLivePositions()
  const tradeFeed = useCodexStore((s) => s.tradeFeed)

  const position = useMemo(
    () => positions.find((p) => getStr(p, 'symbol') === symbol) ?? null,
    [positions, symbol],
  )
  const symbolTrades = useMemo(
    () => tradeFeed.filter((t) => t.symbol === symbol).slice(0, 20),
    [tradeFeed, symbol],
  )

  const pnl = position ? toNum(getField(position, 'pnl')) : null
  const qty = position ? positionQty(position) : null
  const side = position ? getStr(position, 'side').toUpperCase() : ''
  const entry = position ? toNum(getField(position, 'entry_price')) : null
  const current = position ? toNum(getField(position, 'current_price')) : null
  const invested = position ? positionCostBasis(position) : null

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-16"
      onClick={onClose}
    >
      <div
        className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-slate-200 bg-white p-5 shadow-2xl dark:border-slate-700 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className={sectionTitleClass}>Position · {symbol}</p>
            {side && (
              <span
                className={cn(
                  'mt-1 inline-block rounded-md px-2 py-0.5 text-[11px] font-semibold',
                  positionSideBadgeClass(side),
                )}
              >
                {side}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-xl font-bold leading-none text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {position ? (
          <div className="mb-5 grid grid-cols-3 gap-3 text-center">
            <Metric label="qty" value={qty != null ? formatQuantity(qty) : '--'} />
            <Metric label="entry" value={entry != null ? formatUSD(entry) : '--'} />
            <Metric label="current" value={current != null ? formatUSD(current) : '--'} />
            <Metric label="invested" value={invested != null ? formatUSD(invested) : '--'} />
            <Metric
              label="P&L"
              value={pnl != null ? `${pnl >= 0 ? '+' : '-'}${formatUSD(pnl)}` : '--'}
              tone={pnl == null ? undefined : pnl >= 0 ? 'pos' : 'neg'}
            />
          </div>
        ) : (
          <p className={cn(mutedClass, 'mb-5')}>
            This position is no longer open — showing its recent trade history below.
          </p>
        )}

        <p className={cn(sectionTitleClass, 'mb-2')}>Recent trades · {symbol}</p>
        {symbolTrades.length === 0 ? (
          <p className={mutedClass}>
            No trades recorded for {symbol} yet. In memory mode (no database) trade
            history is cleared on restart and rebuilds as new trades close.
          </p>
        ) : (
          <div className="space-y-1">
            {symbolTrades.map((t) => {
              const tpnl = t.pnl
              return (
                <div
                  key={t.id}
                  className="flex items-center justify-between gap-2 rounded border border-slate-200 px-2 py-1.5 font-mono text-xs dark:border-slate-700"
                >
                  <span className="uppercase text-slate-500 dark:text-slate-400">
                    {t.side ?? '--'}
                  </span>
                  <span className="text-slate-600 dark:text-slate-300">
                    {t.entry_price != null ? formatUSD(t.entry_price) : '--'}
                    {' → '}
                    {t.exit_price != null ? formatUSD(t.exit_price) : '--'}
                  </span>
                  {t.grade && (
                    <span className="rounded bg-slate-500/10 px-1.5 py-0.5 text-[10px] text-slate-500">
                      {t.grade}
                    </span>
                  )}
                  <span
                    className={cn(
                      'font-semibold tabular-nums',
                      tpnl == null
                        ? 'text-slate-400'
                        : tpnl >= 0
                          ? 'text-emerald-500'
                          : 'text-rose-500',
                    )}
                  >
                    {tpnl == null ? '--' : `${tpnl >= 0 ? '+' : '-'}${formatUSD(tpnl)}`}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: 'pos' | 'neg' }) {
  return (
    <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
      <p
        className={cn(
          'font-mono text-base tabular-nums',
          tone === 'pos'
            ? 'text-emerald-500'
            : tone === 'neg'
              ? 'text-rose-500'
              : 'text-slate-900 dark:text-slate-100',
        )}
      >
        {value}
      </p>
      <p className={mutedClass}>{label}</p>
    </div>
  )
}
