'use client'

import { useState } from 'react'

import type { AgentInstance, AgentLog, AgentHeartbeat } from '@/stores/useDashboardStore'
import type { ApiHealth } from '@/hooks/useRestPoll'
import { cn } from '@/lib/utils'
import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { apiHealthBadgeClass } from '@/lib/dashboard-helpers'
import { TONE_DOT } from '@/lib/design/sentiment'
import { formatAgeFromMs } from '@/lib/formatters'
import { Button } from '@/components/ui/button'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import type { WiringFreshness } from './shared'

function formatWiringAge(ageMs: number | null): string {
  const age = formatAgeFromMs(ageMs)
  return age === NO_DATA ? UI_COPY.agentsPage.noRecentTimestamp : `last ${age} ago`
}

export interface SystemDiagnosticsProps {
  isInMemoryMode: boolean
  agentStatuses: AgentHeartbeat[]
  agentInstances: AgentInstance[]
  agentLogs: AgentLog[]
  wiringFreshness: WiringFreshness
  apiHealth: ApiHealth
}

/**
 * Data-wiring health — where the dashboard numbers come from. For debugging,
 * so it stays collapsed by default; the DB-connection badge is the one signal
 * worth a glance without expanding.
 */
export function SystemDiagnostics({
  isInMemoryMode,
  agentStatuses,
  agentInstances,
  agentLogs,
  wiringFreshness,
  apiHealth,
}: SystemDiagnosticsProps) {
  const [expanded, setExpanded] = useState(false)
  const apiRows = [
    { label: 'dashboard/state', value: apiHealth.dashboardState },
    { label: 'agent-instances', value: apiHealth.agentInstances },
    { label: 'history/events', value: apiHealth.eventHistory },
  ]
  return (
    <div className={cardClass}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className={sectionTitleClass}>{UI_COPY.agentsPage.diagnosticsTitle}</p>
          <p className={cn(mutedClass, 'mb-2')}>{UI_COPY.agentsPage.diagnosticsSubtitle}</p>
        </div>
        <Button
          variant="outline"
          size="xs"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          {expanded ? UI_COPY.agentsPage.diagnosticsHideDetails : UI_COPY.agentsPage.diagnosticsShowDetails}
        </Button>
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span
          className={cn(
            'flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold',
            isInMemoryMode ? 'bg-warning/10 text-warning' : 'bg-success/10 text-success',
          )}
        >
          <span
            className={cn('inline-block h-2 w-2 rounded-full', isInMemoryMode ? TONE_DOT.warning : TONE_DOT.success)}
          />
          {isInMemoryMode ? UI_COPY.agentsPage.dbMemory : UI_COPY.agentsPage.dbConnected}
        </span>
      </div>

      {expanded && (
        <>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <p className={mutedClass}>
              {UI_COPY.agentsPage.wiringHeartbeats}{' '}
              <span className="font-mono text-foreground/80">{agentStatuses.length}</span>
              <span className="ml-2 text-2xs">{formatWiringAge(wiringFreshness.heartbeatAgeMs)}</span>
            </p>
            <p className={mutedClass}>
              {UI_COPY.agentsPage.wiringLifecycle}{' '}
              <span className="font-mono text-foreground/80">{agentInstances.length}</span>
              <span className="ml-2 text-2xs">{formatWiringAge(wiringFreshness.instanceAgeMs)}</span>
            </p>
            <p className={mutedClass}>
              {UI_COPY.agentsPage.wiringLogs}{' '}
              <span className="font-mono text-foreground/80">{agentLogs.length}</span>
              <span className="ml-2 text-2xs">{formatWiringAge(wiringFreshness.logAgeMs)}</span>
            </p>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {apiRows.map((apiRow) => (
              <span
                key={apiRow.label}
                className={cn(
                  'rounded px-2 py-0.5 text-3xs font-semibold uppercase tracking-caps',
                  apiHealthBadgeClass(apiRow.value),
                )}
              >
                {apiRow.label}: {apiRow.value}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
