'use client'

import { cn } from '@/lib/utils'
import { Panel } from './Panel'
import { formatTimestamp } from '@/lib/formatters'

function actionClass(action: string): string {
  if (action === 'buy') return 'txt-up'
  if (action === 'sell') return 'txt-down'
  if (action === 'reject') return 'text-slate-500 dark:text-slate-500'
  return 'text-slate-600 dark:text-slate-300'
}

/** Recent REAL decisions emitted by the ReasoningAgent (via /decisions). */
export function DecisionsPanel({ decisions }: { decisions: Array<Record<string, unknown>> }) {
  return (
    <Panel title="Agent Decisions" count={decisions.length} bodyClass="overflow-y-auto thin-scroll">
      {decisions.length === 0 ? (
        <div className="flex h-full items-center justify-center py-8 text-[12px] text-slate-500 dark:text-slate-600">
          No agent decisions yet
        </div>
      ) : (
        <div className="divide-y divide-slate-100 dark:divide-slate-800/60">
          {decisions.slice(0, 40).map((d, i) => {
            const action = String(d.action ?? '').toLowerCase()
            const symbol = String(d.symbol ?? '--')
            const conf = Number(d.confidence)
            const ts = formatTimestamp(d.timestamp ? String(d.timestamp) : null)
            return (
              <div
                key={`${String(d.id ?? d.trace_id ?? i)}-${i}`}
                className="grid grid-cols-[1fr_auto] items-center gap-x-2 px-3 py-1.5 font-mono text-[11px] tabular-nums"
              >
                <div className="flex items-center gap-2 truncate">
                  <span className={cn('font-bold uppercase', actionClass(action))}>{action || 'hold'}</span>
                  <span className="font-bold text-slate-900 dark:text-slate-100">{symbol}</span>
                  {Number.isFinite(conf) && <span className="text-slate-500">{(conf * 100).toFixed(0)}%</span>}
                </div>
                <span className="text-right text-slate-500 dark:text-slate-600">{ts}</span>
              </div>
            )
          })}
        </div>
      )}
    </Panel>
  )
}
