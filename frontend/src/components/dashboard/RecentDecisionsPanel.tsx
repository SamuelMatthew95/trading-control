'use client'

import { cn } from '@/lib/utils'
import { cardClass, sectionTitleClass } from '@/lib/dashboard-styles'
import type { DecisionStats } from '@/hooks/useRestPoll'

function formatTimestamp(value?: string | null): string {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleTimeString()
}

function EmptyDecisions() {
  return (
    <div className="flex h-28 items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50/50 dark:border-slate-800 dark:bg-slate-900/30">
      <p className="text-xs font-sans font-medium text-slate-400 dark:text-slate-600">
        No buy/sell decisions yet
      </p>
    </div>
  )
}

export function RecentDecisionsPanel({
  stats,
  recent,
}: {
  stats: DecisionStats | null
  recent: Array<Record<string, unknown>>
}) {
  const actionable = recent.filter((d) => {
    const action = String(d.action ?? '').toLowerCase()
    return action === 'buy' || action === 'sell'
  })

  return (
    <div className={cardClass}>
      <div className="mb-3 flex items-center justify-between">
        <p className={sectionTitleClass}>Recent Decisions</p>
        {stats && (
          <div className="flex items-center gap-3 font-mono text-xs tabular-nums text-slate-500 dark:text-slate-400">
            <span className="text-emerald-600 dark:text-emerald-400">
              Buys: {stats.last_hour.buys}
            </span>
            <span className="text-rose-600 dark:text-rose-400">
              Sells: {stats.last_hour.sells}
            </span>
            <span>Holds: {stats.last_hour.holds}</span>
            <span>Total: {stats.total}</span>
          </div>
        )}
      </div>

      {actionable.length === 0 ? (
        <EmptyDecisions />
      ) : (
        <div className="max-h-64 space-y-2 overflow-y-auto">
          {actionable.slice(0, 10).map((d, index) => {
            const action = String(d.action ?? '').toLowerCase()
            const symbol = String(d.symbol ?? '--')
            const priceNum = Number(d.price)
            const priceTxt = Number.isFinite(priceNum)
              ? `$${priceNum.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
              : '--'
            const confNum = Number(d.confidence)
            const confTxt = Number.isFinite(confNum) ? `${(confNum * 100).toFixed(0)}%` : '--'
            const ts = formatTimestamp(d.timestamp ? String(d.timestamp) : null)
            const badgeClass =
              action === 'buy'
                ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                : 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
            return (
              <div
                key={`${String(d.id ?? d.trace_id ?? index)}-${index}`}
                className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800"
              >
                <div className="flex items-center gap-3">
                  <span className={cn('rounded px-2 py-0.5 text-xs font-black uppercase', badgeClass)}>
                    {action || 'hold'}
                  </span>
                  <span className="font-mono text-sm font-semibold text-slate-900 dark:text-slate-100">
                    {symbol}
                  </span>
                </div>
                <div className="flex items-center gap-3 font-mono text-xs tabular-nums text-slate-600 dark:text-slate-300">
                  <span>{priceTxt}</span>
                  <span className="text-slate-400">·</span>
                  <span>{confTxt}</span>
                  <span className="text-slate-400">·</span>
                  <span>{ts}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
