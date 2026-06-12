'use client'

import { cn } from '@/lib/utils'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { actionTextClass } from '@/lib/dashboard-helpers'
import { Panel } from './Panel'
import { formatTimestamp } from '@/lib/formatters'

/** Recent REAL decisions emitted by the ReasoningAgent (via /decisions). */
export function DecisionsPanel({ decisions }: { decisions: Array<Record<string, unknown>> }) {
  return (
    <Panel title={UI_COPY.panels.agentDecisions} count={decisions.length} bodyClass="overflow-y-auto thin-scroll">
      {decisions.length === 0 ? (
        <div className="flex h-full items-center justify-center py-8 text-xs text-muted-foreground">
          {UI_COPY.empty.agentDecisions}
        </div>
      ) : (
        <div className="divide-y divide-border">
          {decisions.slice(0, 40).map((d, i) => {
            const action = String(d.action ?? '').toLowerCase()
            const symbol = String(d.symbol ?? NO_DATA)
            const conf = Number(d.confidence)
            const ts = formatTimestamp(d.timestamp ? String(d.timestamp) : null)
            return (
              <div
                key={`${String(d.id ?? d.trace_id ?? i)}-${i}`}
                className="grid grid-cols-[1fr_auto] items-center gap-x-2 px-3 py-1.5 font-mono text-2xs tabular-nums"
              >
                <div className="flex items-center gap-2 truncate">
                  <span className={cn('font-bold uppercase', actionTextClass(action))}>
                    {action || UI_COPY.terminal.defaultAction}
                  </span>
                  <span className="font-bold text-foreground">{symbol}</span>
                  {Number.isFinite(conf) && <span className="text-muted-foreground">{(conf * 100).toFixed(0)}%</span>}
                </div>
                <span className="text-right text-muted-foreground/70">{ts}</span>
              </div>
            )
          })}
        </div>
      )}
    </Panel>
  )
}
