'use client'

import { TerminalCard, SectionHeader, StateIndicator } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, type Tone } from '@/lib/state'
import { formatDuration } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import {
  CHIP_BASE,
  ROW_WRAP,
  STRONG_MONO,
  SUB_PANEL_GRID,
} from '@/lib/styles'
import type { ApiHealthState, WiringFreshness } from '@/lib/types'

const API_HEALTH_TONE: Record<ApiHealthState, Tone> = {
  pending: 'muted',
  ok: 'pos',
  error: 'neg',
}

const AGE_INLINE = 'ml-2 text-[11px]'

interface ApiHealthRow {
  label: string
  value: ApiHealthState
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

function ageLabel(age: number | null): string {
  return age == null ? 'No recent timestamp' : `last ${formatDuration(age)} ago`
}

function DiagnosticRow(props: { label: string; value: string; age: number | null }) {
  return (
    <p className={UI_TEXT.muted}>
      {props.label}: <span className={STRONG_MONO}>{props.value}</span>
      <span className={AGE_INLINE}>{ageLabel(props.age)}</span>
    </p>
  )
}

function ApiHealthChip(props: { row: ApiHealthRow }) {
  const tone = API_HEALTH_TONE[props.row.value]
  return (
    <span className={cn(CHIP_BASE, 'tracking-wide', TONE_CLASSES[tone].soft)}>
      {props.row.label}: {props.row.value}
    </span>
  )
}

function buildApiHealthRows(apiHealth: SystemDiagnosticsProps['apiHealth']): ApiHealthRow[] {
  return [
    { label: 'dashboard/state', value: apiHealth.dashboardState },
    { label: 'agent-instances', value: apiHealth.agentInstances },
    { label: 'history/events', value: apiHealth.eventHistory },
  ]
}

export function SystemDiagnosticsPanel(props: SystemDiagnosticsProps) {
  const apiHealthRows = buildApiHealthRows(props.apiHealth)
  return (
    <TerminalCard>
      <SectionHeader title="System Diagnostics" />
      <div className={cn('mb-3', ROW_WRAP)}>
        <StateIndicator
          tone={props.isInMemoryMode ? 'warn' : 'pos'}
          label={props.isInMemoryMode ? 'DB: In-Memory Fallback' : 'DB: Connected'}
        />
      </div>
      <div className={SUB_PANEL_GRID}>
        <DiagnosticRow
          label="Heartbeats (in-memory/Redis)"
          value={String(props.agentStatusesCount)}
          age={props.wiringFreshness.heartbeatAgeMs}
        />
        <DiagnosticRow
          label="Lifecycle rows (DB)"
          value={String(props.agentInstancesCount)}
          age={props.wiringFreshness.instanceAgeMs}
        />
        <DiagnosticRow
          label="Agent logs (DB/WS)"
          value={String(props.agentLogsCount)}
          age={props.wiringFreshness.logAgeMs}
        />
      </div>
      <div className={cn('mt-3', ROW_WRAP)}>
        {apiHealthRows.map((row) => (
          <ApiHealthChip key={row.label} row={row} />
        ))}
      </div>
    </TerminalCard>
  )
}
