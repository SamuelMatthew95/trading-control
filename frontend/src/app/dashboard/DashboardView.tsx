'use client'

import { useMemo, useState } from 'react'
import { UI_COPY } from '@/constants/copy'
import { useDashboardStore, type AgentHeartbeat } from '@/stores/useDashboardStore'
import { useSystemStatus } from '@/hooks/useSystemStatus'
import { useRestPoll } from '@/hooks/useRestPoll'
import { useLivePositions } from '@/hooks/useLivePositions'
import { cn } from '@/lib/utils'
import { parseTimestampMs, toFiniteNum as toFiniteNumber } from '@/lib/formatters'
import { ChallengersPanel } from '@/components/dashboard/ChallengersPanel'
import { LearningConsole } from '@/components/dashboard/LearningConsole'
import { TradingView } from '@/components/dashboard/TradingView'
import { TraceModal } from '@/components/dashboard/TraceModal'
import { ProposalsSection } from '@/components/dashboard/ProposalsSection'
import { LLMDegradedBanner } from '@/components/dashboard/LLMDegradedBanner'
import { SystemDashboard } from '@/components/dashboard/system'
import { AgentsDashboard } from '@/components/dashboard/agents'
import { TradingTerminal } from '@/components/dashboard/terminal'
import { ALL_AGENT_NAMES, canonicalAgentKey } from '@/constants/agents'
import type { AgentSummary } from '@/lib/agent-pipeline'
import { isLifecycleLog } from '@/lib/activity-timeline'
import { systemStatusBadgeClass, agentTierFromStatus } from '@/lib/dashboard-helpers'
import { PageHeader } from '@/components/ui/page-header'
import {
  BackendOfflineBanner,
  BackendOfflineEmptyState,
} from '@/components/dashboard/BackendOfflineBanner'

type Section = 'overview' | 'trading' | 'agents' | 'challengers' | 'learning' | 'proposals' | 'system'

// Page heading copy lives in the central registry (UI_COPY.pages).
const SECTION_META = UI_COPY.pages

// Liveness window mirrors the backend heartbeat contract (api/constants.py):
//   AGENT_STALE_THRESHOLD_SECONDS = 120 → an agent stays "Live" while its last
//   heartbeat is < 2 min old. Agents heartbeat every 15–60s.
const AGENT_LIVE_THRESHOLD_MS = 120_000

function isClosedTrade(order: Record<string, unknown> | null | undefined): boolean {
  if (!order) return false
  const status = String(order.status ?? '').toLowerCase()
  if (status === 'filled' || status === 'closed' || status === 'executed' || status === 'completed') return true
  if (order.filled_at != null) return true
  return false
}

/** Canonical timestamp parsing (formatters.parseTimestampMs) as a Date. */
function parseTimestamp(value: unknown): Date | null {
  const ms = parseTimestampMs(value)
  return ms == null || ms <= 0 ? null : new Date(ms)
}

function parseHeartbeatTimestamp(status: AgentHeartbeat): Date | null {
  const fromIsoField = parseTimestamp(status.last_seen_at)
  if (fromIsoField) return fromIsoField
  const fromEpochField = parseTimestamp(status.last_seen)
  if (fromEpochField) return fromEpochField
  // Backward compatibility for older payloads that (incorrectly) used last_event as a timestamp.
  return parseTimestamp(status.last_event)
}

/** Sort/merge order for agent lifecycle states — healthiest first. */
const AGENT_STATUS_PRIORITY: Record<AgentSummary['status'], number> = {
  Live: 0,
  Stale: 1,
  Error: 2,
  Idle: 3,
}

function pickHigherPriorityStatus(
  current: AgentSummary['status'] | undefined,
  incoming: AgentSummary['status'],
): AgentSummary['status'] {
  if (!current) return incoming
  return AGENT_STATUS_PRIORITY[incoming] < AGENT_STATUS_PRIORITY[current] ? incoming : current
}

export function DashboardView({ section }: { section: Section }) {
  const {
    agentLogs = [],
    orders = [],
    prices = {},
    notifications = [],
    proposals = [],
    tradeFeed = [],
    closedTrades = [],
    riskAlerts = [],
    regime,
    killSwitchActive,
    agentInstances = [],
    performanceSummary,
    dashboardData,
    wsConnected,
    marketTickCount,
    lastMarketSymbol,
    streamStats,
    wsMessageCount,
    wsLastMessageTimestamp,
    wsDiagnostics,
    recentEvents = [],
    agentStatuses = [],
  } = useDashboardStore()

  const [activeTraceId, setActiveTraceId] = useState<string | null>(null)

  const {
    apiHealth,
    systemFeedError,
    backendOffline,
    lastSyncAt,
    llmAvailable,
    llmProvider,
    pricesFetched,
    tradeFeedEmptyReason,
    tradeFeedUpstream,
    decisionStats,
    recentDecisions,
    persistedCounts,
    persistedEvents,
    persistedLogs,
  } = useRestPoll(wsConnected)

  const isInMemoryMode = String((dashboardData as Record<string, unknown> | null)?.mode ?? '').includes('in_memory')
  const baseSystemStatus = useSystemStatus()
  const systemStatus = systemFeedError ? 'error' : baseSystemStatus

  // Backend-offline handling: the store is never wiped on a failed fetch, so
  // last-known data stays rendered behind a dismissible banner (the banner
  // owns its dismissal). Only when this session never loaded anything do we
  // swap the panels for an explanatory empty state (empty panels otherwise
  // read as "everything is broken").
  const hasAnyLoadedData =
    dashboardData != null ||
    orders.length > 0 ||
    tradeFeed.length > 0 ||
    notifications.length > 0
  const lastKnownAt = lastSyncAt ?? dashboardData?.timestamp ?? null

  // Live-marked positions for the System view (P&L re-valued against the stream).
  const livePositions = useLivePositions()

  // Performance summary used by the System view: prefer the API aggregate, fall
  // back to a locally-computed summary when the API response is uniformly zero
  // but the client has closed trades.
  const closedTradePnls = useMemo(
    () =>
      orders
        .filter((order) => isClosedTrade(order))
        .map((order) => toFiniteNumber(order?.pnl))
        .filter((pnl): pnl is number => pnl != null),
    [orders],
  )
  const fallbackPerformanceSummary = useMemo(() => {
    if (closedTradePnls.length === 0) return null
    const total = closedTradePnls.reduce((sum, pnl) => sum + pnl, 0)
    const wins = closedTradePnls.filter((pnl) => pnl > 0).length
    const losses = closedTradePnls.filter((pnl) => pnl < 0).length
    const decided = wins + losses
    return {
      total_pnl: total,
      win_rate: decided > 0 ? wins / decided : 0,
      best_trade: Math.max(...closedTradePnls),
      worst_trade: Math.min(...closedTradePnls),
    }
  }, [closedTradePnls])
  const apiSummaryHasSignal =
    performanceSummary != null &&
    ((performanceSummary.total_pnl ?? 0) !== 0 ||
      (performanceSummary.win_rate ?? 0) !== 0 ||
      (performanceSummary.best_trade ?? 0) !== 0 ||
      (performanceSummary.worst_trade ?? 0) !== 0)
  const resolvedPerformanceSummary = apiSummaryHasSignal
    ? performanceSummary
    : (fallbackPerformanceSummary ?? performanceSummary)

  const realAgents = useMemo(() => {
    const grouped = agentLogs.reduce<Record<string, { displayName: string; count: number; lastSeen: Date | null }>>((acc, log) => {
      // Agent spawn/retire rows (log_type='lifecycle') are not produced output —
      // counting them made idle learning agents read "1 event". Skip them.
      if (isLifecycleLog(log)) return acc
      const name = String(log?.agent_name || log?.agent || '').trim()
      if (!name) return acc
      const agentKey = canonicalAgentKey(name)
      const safeDate = parseTimestamp(log?.timestamp || log?.created_at)
      const existing = acc[agentKey] ?? { displayName: name, count: 0, lastSeen: null }
      const newest = !existing.lastSeen || (safeDate && safeDate > existing.lastSeen) ? safeDate : existing.lastSeen
      acc[agentKey] = { displayName: existing.displayName, count: existing.count + 1, lastSeen: newest }
      return acc
    }, {})

    const now = Date.now()
    const incomingAgents = Object.entries(grouped).map<AgentSummary>(([, data]) => {
      const ageMs = data.lastSeen ? now - data.lastSeen.getTime() : Infinity
      const status: AgentSummary['status'] = ageMs <= AGENT_LIVE_THRESHOLD_MS ? 'Live' : 'Idle'
      const tier: AgentSummary['tier'] = status === 'Live' ? 'active' : data.count > 0 ? 'challenger' : 'inactive'
      return {
        name: data.displayName,
        eventCount: data.count,
        lastSeen: data.lastSeen,
        status,
        tier,
        source: 'realtime',
      }
    })

    const normalizedByName = new Map(incomingAgents.map((agent) => [canonicalAgentKey(agent.name), agent]))
    for (const status of agentStatuses) {
      const agentKey = canonicalAgentKey(status.name)
      const existing = normalizedByName.get(agentKey)
      const statusDate = parseHeartbeatTimestamp(status)
      const ageMs = statusDate ? now - statusDate.getTime() : Number.POSITIVE_INFINITY
      const mappedStatus: AgentSummary['status'] = ageMs <= AGENT_LIVE_THRESHOLD_MS ? 'Live' : 'Idle'
      const mergedStatus = pickHigherPriorityStatus(existing?.status, mappedStatus)
      const lastSeen = [existing?.lastSeen, statusDate]
        .filter((d): d is Date => d instanceof Date)
        .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
      normalizedByName.set(agentKey, {
        name: existing?.name ?? status.name,
        eventCount: status.event_count ?? existing?.eventCount ?? 0,
        lastSeen,
        status: mergedStatus,
        tier: agentTierFromStatus(mergedStatus),
        source: existing ? 'hybrid' : 'realtime',
      })
    }

    for (const inst of agentInstances) {
      const agentKey = canonicalAgentKey(inst.pool_name)
      const existing = normalizedByName.get(agentKey)
      const startedDate = parseTimestamp(inst.started_at)
      const mappedStatus: AgentSummary['status'] = 'Idle'
      const mergedStatus = pickHigherPriorityStatus(existing?.status, mappedStatus)
      const lastSeen = [existing?.lastSeen, startedDate]
        .filter((d): d is Date => d instanceof Date)
        .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
      normalizedByName.set(agentKey, {
        name: existing?.name ?? inst.pool_name,
        eventCount: existing?.eventCount ?? inst.event_count ?? 0,
        lastSeen,
        status: mergedStatus,
        tier: agentTierFromStatus(mergedStatus),
        source: existing ? 'hybrid' : 'persisted',
      })
    }

    for (const name of ALL_AGENT_NAMES) {
      const agentKey = canonicalAgentKey(name)
      if (!normalizedByName.has(agentKey)) {
        normalizedByName.set(agentKey, {
          name,
          eventCount: 0,
          lastSeen: null,
          status: 'Idle',
          tier: 'inactive',
          source: 'persisted',
        })
      }
    }

    return Array.from(normalizedByName.values()).sort((a, b) => {
      const byStatus = AGENT_STATUS_PRIORITY[a.status] - AGENT_STATUS_PRIORITY[b.status]
      if (byStatus !== 0) return byStatus
      return a.name.localeCompare(b.name)
    })
  }, [agentLogs, agentStatuses, agentInstances])

  const wiringFreshness = useMemo(() => {
    const now = Date.now()
    const latestHeartbeat = agentStatuses
      .map((row) => parseHeartbeatTimestamp(row)?.getTime() ?? Number.NaN)
      .filter((ts) => Number.isFinite(ts))
      .sort((a, b) => b - a)[0]
    const latestInstance = agentInstances
      .map((row) => new Date(String(row.started_at || '')).getTime())
      .filter((ts) => Number.isFinite(ts))
      .sort((a, b) => b - a)[0]
    const latestLog = agentLogs
      .map((row) => new Date(String(row.timestamp || row.created_at || '')).getTime())
      .filter((ts) => Number.isFinite(ts))
      .sort((a, b) => b - a)[0]

    return {
      heartbeatAgeMs: latestHeartbeat ? now - latestHeartbeat : null,
      instanceAgeMs: latestInstance ? now - latestInstance : null,
      logAgeMs: latestLog ? now - latestLog : null,
    }
  }, [agentStatuses, agentInstances, agentLogs])

  const memoryBanner = dashboardData?.degraded_mode ? (
    <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
      <span className="mt-0.5 shrink-0" aria-hidden>⚠</span>
      <span>
        <strong>{UI_COPY.banners.memoryModeTitle}</strong> {UI_COPY.banners.memoryModeUnavailable}
        {dashboardData.degraded_reason === 'db_unavailable' ? UI_COPY.banners.memoryModeDbReason : ''}.
        {' '}{UI_COPY.banners.memoryModeBody}
      </span>
    </div>
  ) : null

  // Overview is the full-bleed trading terminal — its own dark surface with the
  // account chrome living in the shell header, so it intentionally skips the
  // shared light section frame used by every other section.
  if (section === 'overview') {
    return (
      <div className="min-h-[calc(100vh-3rem)] bg-background text-foreground">
        <div className="space-y-2 px-2 pt-2 empty:hidden">
          <LLMDegradedBanner />
          {memoryBanner}
          {/* Backend unreachable — keep last-known data visible, never blank panels */}
          <BackendOfflineBanner
            active={backendOffline && hasAnyLoadedData}
            lastKnownAt={lastKnownAt}
          />
        </div>
        {backendOffline && !hasAnyLoadedData ? (
          <div className="px-2 pt-2">
            <BackendOfflineEmptyState />
          </div>
        ) : (
          <TradingTerminal recentDecisions={recentDecisions} />
        )}
        {activeTraceId && <TraceModal traceId={activeTraceId} onClose={() => setActiveTraceId(null)} />}
      </div>
    )
  }

  const contentBySection = (
    <>
      {section === 'trading' && (
        <TradingView
          setActiveTraceId={setActiveTraceId}
          tradeFeedEmptyReason={tradeFeedEmptyReason}
          tradeFeedUpstream={tradeFeedUpstream}
        />
      )}

      {section === 'agents' && (
        <AgentsDashboard
          realAgents={realAgents}
          wiringFreshness={wiringFreshness}
          agentStatuses={agentStatuses}
          agentInstances={agentInstances}
          agentLogs={agentLogs}
          notifications={notifications}
          proposals={proposals}
          decisionStats={decisionStats}
          recentDecisions={recentDecisions}
          recentEvents={recentEvents}
          closedTradesCount={Math.max(closedTrades.length, tradeFeed.filter((t) => t.pnl != null).length)}
          apiHealth={apiHealth}
          marketTickCount={marketTickCount}
          lastMarketSymbol={lastMarketSymbol}
          streamStats={streamStats}
          wsConnected={wsConnected}
          isInMemoryMode={isInMemoryMode}
        />
      )}

      {section === 'challengers' && <ChallengersPanel />}

      {section === 'learning' && <LearningConsole setActiveTraceId={setActiveTraceId} />}

      {section === 'proposals' && <ProposalsSection />}

      {section === 'system' && (
        <SystemDashboard
          wsConnected={wsConnected}
          wsMessageCount={wsMessageCount}
          wsLastMessageTimestamp={wsLastMessageTimestamp}
          wsDiagnostics={wsDiagnostics}
          streamStats={streamStats}
          recentEvents={recentEvents}
          agentStatuses={agentStatuses}
          prices={prices}
          positions={livePositions}
          tradeFeed={tradeFeed}
          orders={orders}
          agentLogs={agentLogs}
          notifications={notifications}
          proposals={proposals}
          riskAlerts={riskAlerts}
          pricesFetched={pricesFetched}
          isInMemoryMode={isInMemoryMode}
          resolvedPerformanceSummary={resolvedPerformanceSummary}
          apiHealth={apiHealth}
          systemFeedError={systemFeedError}
          llmAvailable={llmAvailable}
          llmProvider={llmProvider}
          persistedCounts={persistedCounts}
          persistedEvents={persistedEvents}
          persistedLogs={persistedLogs}
          regime={regime}
          killSwitchActive={killSwitchActive}
          setActiveTraceId={setActiveTraceId}
        />
      )}
    </>
  )

  return (
    <div className="min-h-screen bg-background pb-20 text-foreground lg:pb-4">
      <main className="mx-auto max-w-screen-2xl space-y-3 px-3 py-4 sm:px-4">
        <PageHeader {...SECTION_META[section]} />
        <div
          className={cn(
            'rounded-lg border px-3 py-2 text-xs font-semibold uppercase tracking-caps',
            systemStatusBadgeClass(systemStatus),
          )}
        >
          {UI_COPY.pages.statusLabel} {systemStatus}
        </div>
        {/* Reasoning-LLM degraded/down — page-level indicator (fail-closed warning) */}
        <LLMDegradedBanner />
        {/* Persistence / memory-mode banner — single page-level indicator */}
        {memoryBanner}
        {/* Backend unreachable — keep last-known data visible, never blank panels */}
        <BackendOfflineBanner
          active={backendOffline && hasAnyLoadedData}
          lastKnownAt={lastKnownAt}
        />
        {backendOffline && !hasAnyLoadedData ? <BackendOfflineEmptyState /> : contentBySection}
      </main>

      {activeTraceId && <TraceModal traceId={activeTraceId} onClose={() => setActiveTraceId(null)} />}
    </div>
  )
}
