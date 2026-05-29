'use client'

import { useEffect, useState } from 'react'

import {
  useCodexStore,
  type AgentInstance,
  type AgentLog,
  type AgentStatus,
  type Notification,
  type Proposal,
  type StreamStat,
} from '@/stores/useCodexStore'
import type { ApiHealth, DecisionStats } from '@/hooks/useRestPoll'
import type { AgentSummary } from '@/lib/agent-pipeline'
import { cn } from '@/lib/utils'
import { formatTimeAgo, formatTimestamp, parseTimestampMs, sanitizeValue } from '@/lib/formatters'
import { countRecentNotifications, lastNotificationLabel } from '@/lib/notification-metrics'
import { agentDisplayName } from '@/constants/agents'
import { STREAM_MARKET_EVENTS, STREAM_MARKET_TICKS } from '@/constants/streams'
import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { agentStatusDotClass, apiHealthBadgeClass } from '@/lib/dashboard-helpers'
import { formatAgeFromMs } from '@/components/dashboard/system/helpers'
import { AgentPipeline } from '@/components/dashboard/AgentPipeline'
import { LLMHealthPanel } from '@/components/dashboard/LLMHealthPanel'
import { LearningLoopPanel } from '@/components/dashboard/LearningLoopPanel'
import { RecentDecisionsPanel } from '@/components/dashboard/RecentDecisionsPanel'
import { NotificationFeed } from '@/components/dashboard/NotificationFeed'
import { KpiCard } from './KpiCard'

// ── Timing windows ──────────────────────────────────────────────────────────
const MARKET_LIVE_WINDOW_MS = 60_000
const NOTIFICATION_RECENT_WINDOW_MS = 3_600_000 // 1 hour
const AGENT_DATA_TIMEOUT_MS = 10_000

export interface WiringFreshness {
  heartbeatAgeMs: number | null
  instanceAgeMs: number | null
  logAgeMs: number | null
}

export interface AgentsDashboardProps {
  realAgents: AgentSummary[]
  wiringFreshness: WiringFreshness
  agentStatuses: AgentStatus[]
  agentInstances: AgentInstance[]
  agentLogs: AgentLog[]
  notifications: Notification[]
  proposals: Proposal[]
  decisionStats: DecisionStats | null
  recentDecisions: Array<Record<string, unknown>>
  apiHealth: ApiHealth
  marketTickCount: number
  lastMarketSymbol: string | null
  streamStats: Record<string, StreamStat>
  wsConnected: boolean
  isInMemoryMode: boolean
}

// ── Agents-only helpers ───────────────────────────────────────────────────────

function formatAgentSource(source: AgentSummary['source']): string {
  if (source === 'realtime') return 'Realtime'
  if (source === 'persisted') return 'Persisted'
  return 'Hybrid'
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m`
}

function formatWiringAge(ageMs: number | null): string {
  const age = formatAgeFromMs(ageMs)
  return age === '--' ? 'No recent timestamp' : `last ${age} ago`
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex min-h-28 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/50 px-4 py-10 dark:border-slate-800 dark:bg-slate-900/30">
      <p className="text-xs font-sans font-medium text-slate-400 dark:text-slate-600">{message}</p>
    </div>
  )
}

export function AgentsDashboard(props: AgentsDashboardProps) {
  const {
    realAgents,
    wiringFreshness,
    agentStatuses,
    agentInstances,
    agentLogs,
    notifications,
    proposals,
    decisionStats,
    recentDecisions,
    apiHealth,
    marketTickCount,
    lastMarketSymbol,
    streamStats,
    wsConnected,
    isInMemoryMode,
  } = props

  // Only surface "no agents" after a grace period — agent data can arrive a beat
  // after the WebSocket connects.
  const [showNoAgentDataMessage, setShowNoAgentDataMessage] = useState(false)
  useEffect(() => {
    if (!wsConnected || realAgents.length > 0) {
      setShowNoAgentDataMessage(false)
      return
    }
    const timer = setTimeout(() => {
      const state = useCodexStore.getState()
      const hasAgentData =
        state.agentLogs.length > 0 || state.agentStatuses.length > 0 || state.agentInstances.length > 0
      if (!hasAgentData && state.wsConnected) setShowNoAgentDataMessage(true)
    }, AGENT_DATA_TIMEOUT_MS)
    return () => clearTimeout(timer)
  }, [realAgents.length, wsConnected])

  const liveAgentCount = realAgents.filter((agent) => agent.status === 'Live').length
  const recentNotificationCount = countRecentNotifications(notifications, NOTIFICATION_RECENT_WINDOW_MS)

  const marketTs =
    streamStats?.[STREAM_MARKET_TICKS]?.lastMessageTimestamp ??
    streamStats?.[STREAM_MARKET_EVENTS]?.lastMessageTimestamp ??
    null
  const marketTsMs = parseTimestampMs(marketTs)
  const marketLive =
    marketTsMs != null ? Date.now() - marketTsMs < MARKET_LIVE_WINDOW_MS : marketTickCount > 0 && wsConnected

  // `decisionStats` may transiently be a partial `{}` while the first poll lands.
  const decisionHour = decisionStats?.last_hour
  const decisionsLastHour = decisionHour ? decisionHour.buys + decisionHour.sells + decisionHour.holds : null
  const decisionBreakdown = decisionHour
    ? `${decisionHour.buys} buy · ${decisionHour.sells} sell · ${decisionHour.holds} hold`
    : 'No decision data yet'

  return (
    <div className="space-y-4">
      <AgentPipeline
        agents={realAgents}
        marketTickCount={marketTickCount}
        lastMarketSymbol={lastMarketSymbol}
        marketLive={marketLive}
        decisionStats={decisionStats}
        proposalsCount={proposals.length}
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KpiCard
          label="Agents Online"
          value={sanitizeValue(liveAgentCount)}
          lines={[`${realAgents.length} reporting · live = heartbeat < 10s`]}
        />
        <KpiCard
          label="Market Data"
          value={sanitizeValue(marketTickCount)}
          lines={[`${lastMarketSymbol ?? '—'} · ${marketLive ? 'streaming' : 'idle'}`]}
        />
        <KpiCard label="Decisions · 1h" value={sanitizeValue(decisionsLastHour)} lines={[decisionBreakdown]} />
        <KpiCard
          label="Notifications · 1h"
          value={sanitizeValue(recentNotificationCount)}
          lines={[`${notifications.length} stored (max 200)`, lastNotificationLabel(notifications)]}
        />
      </div>

      <LLMHealthPanel />

      <LearningLoopPanel />

      <div className={cardClass}>
        <p className={sectionTitleClass}>Agent Status</p>
        <p className={cn(mutedClass, 'mb-3')}>Live heartbeat detail for every agent in the pipeline above.</p>
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800">
                {['Agent', 'Status', 'Source', 'Events', 'Last Seen'].map((head) => (
                  <th
                    key={head}
                    className="px-2 py-2 text-left text-xs font-sans font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400"
                  >
                    {head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {showNoAgentDataMessage ? (
                <tr>
                  <td colSpan={5} className="px-2 py-8">
                    <EmptyState message="No active agents" />
                  </td>
                </tr>
              ) : (
                realAgents.map((agent) => (
                  <tr key={agent.name} className="border-t border-slate-200 py-2 dark:border-slate-800">
                    <td className="px-2 py-2 text-sm font-sans text-slate-900 dark:text-slate-100">
                      {agentDisplayName(agent.name)}
                    </td>
                    <td className="px-2 py-2 text-xs font-sans">
                      <span className="inline-flex items-center gap-2">
                        <span className={cn('h-2 w-2 rounded-full', agentStatusDotClass(agent.status))} />
                        <span className="text-slate-700 dark:text-slate-300">{agent.status}</span>
                      </span>
                    </td>
                    <td className="px-2 py-2 text-xs font-sans text-slate-700 dark:text-slate-300">
                      {formatAgentSource(agent.source)}
                    </td>
                    <td className="px-2 py-2 text-right text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">
                      {agent.realtimeCount + agent.persistedCount > 0 ? (
                        <>{(agent.realtimeCount + agent.persistedCount).toLocaleString()} events</>
                      ) : (
                        <span className="text-slate-400 dark:text-slate-600">—</span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">
                      {agent.lastSeen ? formatTimeAgo(agent.lastSeen) : '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className={cardClass}>
        <p className={cn(sectionTitleClass, 'mb-3')}>Agent Instances</p>
        {agentInstances.length === 0 ? (
          <div className="space-y-2">
            <EmptyState message="No instances registered yet" />
            {agentStatuses.some((agent) => String(agent.status).toUpperCase() === 'ACTIVE') && (
              <p className="text-xs font-sans text-amber-600 dark:text-amber-400">
                Agents are reporting ACTIVE heartbeats, but no lifecycle records were returned. Check
                agent_instances DB writes.
              </p>
            )}
          </div>
        ) : (
          <div className="max-h-48 overflow-y-auto">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-800">
                  {['Instance Key', 'Pool', 'Status', 'Events', 'Uptime', 'Started'].map((head) => (
                    <th
                      key={head}
                      className="px-2 py-1.5 text-left text-xs font-sans font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400"
                    >
                      {head}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {agentInstances.map((inst) => {
                  const isActive = inst.status === 'active'
                  return (
                    <tr key={inst.id} className="border-t border-slate-200 dark:border-slate-800">
                      <td className="px-2 py-1.5 text-xs font-mono text-slate-900 dark:text-slate-100">
                        {inst.instance_key}
                      </td>
                      <td className="px-2 py-1.5 text-xs font-sans text-slate-600 dark:text-slate-400">
                        {inst.pool_name}
                      </td>
                      <td className="px-2 py-1.5 text-xs font-sans">
                        <span className="inline-flex items-center gap-1.5">
                          <span className={cn('h-2 w-2 rounded-full', isActive ? 'bg-emerald-500' : 'bg-slate-400')} />
                          <span className={isActive ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-500'}>
                            {inst.status}
                          </span>
                        </span>
                      </td>
                      <td className="px-2 py-1.5 text-right text-xs font-mono tabular-nums text-slate-900 dark:text-slate-100">
                        {inst.event_count}
                      </td>
                      <td className="px-2 py-1.5 text-xs font-mono tabular-nums text-slate-700 dark:text-slate-300">
                        {formatUptime(inst.uptime_seconds)}
                      </td>
                      <td className="px-2 py-1.5 text-xs font-mono text-slate-500">{formatTimestamp(inst.started_at)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <RecentDecisionsPanel stats={decisionStats} recent={recentDecisions} />

      <NotificationFeed notifications={notifications} wsConnected={wsConnected} />

      <div className={cardClass}>
        <p className={sectionTitleClass}>System Diagnostics</p>
        <p className={cn(mutedClass, 'mb-2')}>Data-wiring health — where these numbers come from. For debugging.</p>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span
            className={cn(
              'flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold',
              isInMemoryMode ? 'bg-amber-400/10 text-amber-500' : 'bg-emerald-500/10 text-emerald-500',
            )}
          >
            <span
              className={cn('inline-block h-2 w-2 rounded-full', isInMemoryMode ? 'bg-amber-400' : 'bg-emerald-500')}
            />
            {isInMemoryMode ? 'DB: In-Memory Fallback' : 'DB: Connected'}
          </span>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <p className={mutedClass}>
            Heartbeats (in-memory/Redis):{' '}
            <span className="font-mono text-slate-700 dark:text-slate-200">{agentStatuses.length}</span>
            <span className="ml-2 text-[11px]">{formatWiringAge(wiringFreshness.heartbeatAgeMs)}</span>
          </p>
          <p className={mutedClass}>
            Lifecycle rows (DB):{' '}
            <span className="font-mono text-slate-700 dark:text-slate-200">{agentInstances.length}</span>
            <span className="ml-2 text-[11px]">{formatWiringAge(wiringFreshness.instanceAgeMs)}</span>
          </p>
          <p className={mutedClass}>
            Agent logs (DB/WS):{' '}
            <span className="font-mono text-slate-700 dark:text-slate-200">{agentLogs.length}</span>
            <span className="ml-2 text-[11px]">{formatWiringAge(wiringFreshness.logAgeMs)}</span>
          </p>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {[
            { label: 'dashboard/state', value: apiHealth.dashboardState },
            { label: 'agent-instances', value: apiHealth.agentInstances },
            { label: 'history/events', value: apiHealth.eventHistory },
          ].map((apiRow) => (
            <span
              key={apiRow.label}
              className={cn(
                'rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
                apiHealthBadgeClass(apiRow.value),
              )}
            >
              {apiRow.label}: {apiRow.value}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
