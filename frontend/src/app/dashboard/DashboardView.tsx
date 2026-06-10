'use client'

import { useMemo, useState } from 'react'
import { UI_COPY } from '@/constants/copy'
import { useDashboardStore, type AgentHeartbeat } from '@/stores/useDashboardStore'
import { useSystemStatus } from '@/hooks/useSystemStatus'
import { useRestPoll } from '@/hooks/useRestPoll'
import { useLivePositions } from '@/hooks/useLivePositions'
import { cn } from '@/lib/utils'
import { toFiniteNum as toFiniteNumber } from '@/lib/formatters'
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

type Section = 'overview' | 'trading' | 'agents' | 'learning' | 'proposals' | 'system'

const SECTION_META: Record<Section, { eyebrow: string; title: string; description: string }> = {
  overview: {
    eyebrow: 'Trading terminal',
    title: 'Live equities trading desk',
    description: 'Watchlist, chart, order book, ticket, and blotter in one dense terminal.',
  },
  trading: {
    eyebrow: 'Execution',
    title: 'Trades, fills, and traceable execution',
    description: 'Monitor open risk, fills, grades, and execution provenance without decorative cards.',
  },
  agents: {
    eyebrow: 'Runtime agents',
    title: 'Agent health and production activity',
    description: 'Inspect agent heartbeats, streams, decisions, and diagnostics in a dense operations layout.',
  },
  learning: {
    eyebrow: 'Learning loop',
    title: 'Performance attribution and learning outcomes',
    description: 'Review outcomes, model performance, and learning-loop movement with clear evidence.',
  },
  proposals: {
    eyebrow: 'Proposal review',
    title: 'Candidate changes and challenger verdicts',
    description: 'Approve or reject strategy mutations from a table-first queue with explicit expected impact.',
  },
  system: {
    eyebrow: 'Command Center',
    title: 'Decisions, risk, execution, and traceability',
    description: 'A live view of what the system is thinking, doing, and changing right now.',
  },
}

function SectionHeader({ section }: { section: Section }) {
  const meta = SECTION_META[section]
  return (
    <section className="rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm shadow-slate-900/5 dark:border-slate-800/80 dark:bg-slate-950/90 dark:shadow-black/20">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{meta.eyebrow}</p>
      <div className="mt-1 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-white">{meta.title}</h1>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500 dark:text-slate-400">{meta.description}</p>
        </div>
      </div>
    </section>
  )
}

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

function parseTimestamp(value: unknown): Date | null {
  if (value == null) return null
  if (value instanceof Date) {
    const t = value.getTime()
    return Number.isNaN(t) || t <= 0 ? null : value
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || value <= 0) return null
    const ms = value > 10_000_000_000 ? value : value * 1000
    const d = new Date(ms)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const raw = String(value).trim()
  if (!raw || raw === '0') return null
  if (/^\d+(\.\d+)?$/.test(raw)) {
    const num = Number(raw)
    if (Number.isFinite(num) && num > 0) {
      const ms = num > 10_000_000_000 ? num : num * 1000
      const d = new Date(ms)
      if (!Number.isNaN(d.getTime())) return d
    }
    return null
  }
  const d = new Date(raw)
  if (Number.isNaN(d.getTime()) || d.getTime() <= 0) return null
  return d
}

function parseHeartbeatTimestamp(status: AgentHeartbeat): Date | null {
  const fromIsoField = parseTimestamp(status.last_seen_at)
  if (fromIsoField) return fromIsoField
  const fromEpochField = parseTimestamp(status.last_seen)
  if (fromEpochField) return fromEpochField
  // Backward compatibility for older payloads that (incorrectly) used last_event as a timestamp.
  return parseTimestamp(status.last_event)
}

function pickHigherPriorityStatus(
  current: AgentSummary['status'] | undefined,
  incoming: AgentSummary['status'],
): AgentSummary['status'] {
  if (!current) return incoming
  const priority: Record<AgentSummary['status'], number> = {
    Live: 0,
    Stale: 1,
    Error: 2,
    Idle: 3,
  }
  return priority[incoming] < priority[current] ? incoming : current
}

export function DashboardView({ section }: { section: Section }) {
  const {
    agentLogs = [],
    orders = [],
    prices = {},
    notifications = [],
    proposals = [],
    tradeFeed = [],
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

    const priority: Record<AgentSummary['status'], number> = {
      Live: 0,
      Stale: 1,
      Error: 2,
      Idle: 3,
    }

    return Array.from(normalizedByName.values()).sort((a, b) => {
      const byStatus = priority[a.status] - priority[b.status]
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
      <span className="mt-0.5 shrink-0">⚠</span>
      <span>
        <strong>{UI_COPY.banners.memoryModeTitle}</strong> — database unavailable
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
      <div className="min-h-[calc(100vh-3rem)] bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
        <div className="space-y-2 px-2 pt-2 empty:hidden">
          <LLMDegradedBanner />
          {memoryBanner}
        </div>
        <TradingTerminal recentDecisions={recentDecisions} />
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
          apiHealth={apiHealth}
          marketTickCount={marketTickCount}
          lastMarketSymbol={lastMarketSymbol}
          streamStats={streamStats}
          wsConnected={wsConnected}
          isInMemoryMode={isInMemoryMode}
        />
      )}

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
    <div className="min-h-screen bg-slate-100 pb-20 text-slate-900 dark:bg-slate-950 dark:text-slate-100 lg:pb-4">
      <main className={cn('mx-auto space-y-3 px-3 py-4 sm:px-4', 'max-w-screen-2xl')}>
        <SectionHeader section={section} />
        <div
          className={cn(
            'rounded-lg border px-3 py-2 text-xs font-semibold uppercase tracking-widest',
            systemStatusBadgeClass(systemStatus),
          )}
        >
          System Status: {systemStatus}
        </div>
        {/* Reasoning-LLM degraded/down — page-level indicator (fail-closed warning) */}
        <LLMDegradedBanner />
        {/* Persistence / memory-mode banner — single page-level indicator */}
        {memoryBanner}
        {contentBySection}
      </main>

      {activeTraceId && <TraceModal traceId={activeTraceId} onClose={() => setActiveTraceId(null)} />}
    </div>
  )
}
