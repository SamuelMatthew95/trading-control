'use client'

import { TerminalCard, SectionHeader, StateIndicator } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, type Tone } from '@/lib/state'
import { formatDuration } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import type { ApiHealthState, WiringFreshness } from '@/lib/types'

const API_HEALTH_TONE: Record<ApiHealthState, Tone> = {
  pending: 'muted',
  ok: 'pos',
  error: 'neg',
}

interface SystemDiagnosticsProps {
  isInMemoryMode: boolean
  agentStatusesCount: number
  agentInstancesCount: number
  agentLogsCount: number
  wiringFreshness: WiringFreshness
  apiHealth: {
    dashboardState: ApiHealthState
    agentInstances: ApiHealthState
    eventHistory: ApiHealthState
  }
}

export function SystemDiagnosticsPanel({
  isInMemoryMode,
  agentStatusesCount,
  agentInstancesCount,
  agentLogsCount,
  wiringFreshness,
  apiHealth,
}: SystemDiagnosticsProps) {
  return (
    <TerminalCard>
      <SectionHeader title="System Diagnostics" />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <StateIndicator
          tone={isInMemoryMode ? 'warn' : 'pos'}
          label={isInMemoryMode ? 'DB: In-Memory Fallback' : 'DB: Connected'}
        />
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <DiagnosticRow
          label="Heartbeats (in-memory/Redis)"
          value={String(agentStatusesCount)}
          age={wiringFreshness.heartbeatAgeMs}
        />
        <DiagnosticRow
          label="Lifecycle rows (DB)"
          value={String(agentInstancesCount)}
          age={wiringFreshness.instanceAgeMs}
        />
        <DiagnosticRow
          label="Agent logs (DB/WS)"
          value={String(agentLogsCount)}
          age={wiringFreshness.logAgeMs}
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {(
          [
            { label: 'dashboard/state', value: apiHealth.dashboardState },
            { label: 'agent-instances', value: apiHealth.agentInstances },
            { label: 'history/events', value: apiHealth.eventHistory },
          ] as const
        ).map((row) => (
          <span
            key={row.label}
            className={cn(
              'rounded-[4px] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
              TONE_CLASSES[API_HEALTH_TONE[row.value]].soft,
            )}
          >
            {row.label}: {row.value}
          </span>
        ))}
      </div>
    </TerminalCard>
  )
}

function DiagnosticRow({
  label,
  value,
  age,
}: {
  label: string
  value: string
  age: number | null
}) {
  return (
    <p className={UI_TEXT.muted}>
      {label}: <span className="font-mono text-slate-700 dark:text-slate-200">{value}</span>
      <span className="ml-2 text-[11px]">
        {age == null ? 'No recent timestamp' : `last ${formatDuration(age)} ago`}
      </span>
    </p>
  )
}
