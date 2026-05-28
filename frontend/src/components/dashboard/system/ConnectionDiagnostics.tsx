'use client'

import { cardClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { apiHealthBadgeClass } from '@/lib/dashboard-helpers'
import { cn } from '@/lib/utils'

import { formatTimestamp, resolveWsUrl } from './helpers'
import type { ApiHealth, WsDiagnosticsLike } from './types'

interface DiagnosticRowProps {
  label: string
  value: string
  valueClass?: string
}

function DiagnosticRow({ label, value, valueClass: vc }: DiagnosticRowProps) {
  return (
    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p
        className={cn(
          'mt-1 text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100',
          vc,
        )}
      >
        {value}
      </p>
    </div>
  )
}

export interface ConnectionDiagnosticsProps {
  wsConnected: boolean
  wsLastMessageTimestamp: string | null
  wsDiagnostics: WsDiagnosticsLike
  throughput: number
  pricesCount: number
  pricesFetched: boolean
  apiHealth: ApiHealth
}

export function ConnectionDiagnostics(props: ConnectionDiagnosticsProps) {
  const {
    wsConnected,
    wsLastMessageTimestamp,
    wsDiagnostics,
    throughput,
    pricesCount,
    pricesFetched,
    apiHealth,
  } = props

  const apiRows = [
    { label: 'dashboard/state', value: apiHealth.dashboardState },
    { label: 'agent-instances', value: apiHealth.agentInstances },
    { label: 'history/events', value: apiHealth.eventHistory },
  ] as const

  return (
    <div className={cn(cardClass, 'lg:col-span-2')}>
      <p className={cn(sectionTitleClass, 'mb-3')}>Connection Diagnostics</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <DiagnosticRow
          label="WebSocket Status"
          value={wsConnected ? '● Connected' : '● Disconnected'}
          valueClass={wsConnected ? 'text-emerald-500' : 'text-rose-500'}
        />
        <DiagnosticRow
          label="API Base"
          value={process.env.NEXT_PUBLIC_API_URL ?? '/api (fallback)'}
          valueClass="text-xs break-all"
        />
        <DiagnosticRow
          label="WebSocket URL"
          value={resolveWsUrl()}
          valueClass="text-xs break-all"
        />
        <DiagnosticRow
          label="Prices Source"
          value={`${pricesCount} symbols ${pricesFetched ? '(loaded)' : '(waiting)'}`}
        />
        <DiagnosticRow label="Message Rate" value={`${throughput.toFixed(2)} msg/sec`} />
        <DiagnosticRow
          label="Last Message"
          value={formatTimestamp(wsLastMessageTimestamp)}
        />
        <DiagnosticRow
          label="Reconnect Attempts"
          value={String(wsDiagnostics.reconnectAttempts)}
        />
        <DiagnosticRow label="Last Error" value={wsDiagnostics.lastError ?? 'None'} />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {apiRows.map((row) => (
          <span
            key={row.label}
            className={cn(
              'rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
              apiHealthBadgeClass(row.value),
            )}
          >
            {row.label}: {row.value}
          </span>
        ))}
      </div>
    </div>
  )
}
