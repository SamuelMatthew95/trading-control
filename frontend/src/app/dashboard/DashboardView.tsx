'use client'

import { useEffect, useMemo, useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { useSystemStatus } from '@/hooks/useSystemStatus'
import { useDashboardData } from '@/hooks/useDashboardData'
import { TONE_CLASSES, toneForSystemStatus } from '@/lib/state'
import { canonicalAgentKey } from '@/lib/constants/agentStates'
import { toFiniteNumber } from '@/lib/format'
import { cn } from '@/lib/utils'
import { UI_RADIUS } from '@/lib/constants/ui'
import {
  buildAgentSummaries,
  buildDashboardSummary,
  buildFallbackPerformanceSummary,
  buildTradeFeedAggregates,
  buildWiringFreshness,
} from '@/lib/dashboard/selectors'
import {
  buildCleanGradeHistory,
  buildLearningSummary,
  buildPipelineStages,
} from '@/lib/dashboard/learning'
import {
  AgentsSection,
  LearningSection,
  OverviewSection,
  SystemSection,
  TradingSection,
  TraceModal,
} from '@/components/dashboard/sections'
import type { Section } from './types'

const NO_AGENT_DATA_DELAY_MS = 10_000
const PIPELINE_HEALTHY_LATENCY_MS = 15_000

export function DashboardView({ section }: { section: Section }) {
  const {
    agentLogs = [],
    learningEvents = [],
    orders = [],
    prices = {},
    positions = [],
    systemMetrics = [],
    notifications = [],
    proposals = [],
    tradeFeed = [],
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
    updateProposalStatus,
  } = useCodexStore()

  const data = useDashboardData(wsConnected)
  const baseSystemStatus = useSystemStatus()
  const systemStatus = data.systemFeedError ? 'error' : baseSystemStatus

  const [activeTraceId, setActiveTraceId] = useState<string | null>(null)
  const [showNoAgentDataMessage, setShowNoAgentDataMessage] = useState(false)

  // ── Derived view-models ─────────────────────────────────────────────────
  const summary = useMemo(
    () => buildDashboardSummary(orders, positions, systemMetrics, dashboardData as Record<string, unknown> | null),
    [orders, positions, systemMetrics, dashboardData],
  )

  const fallbackPerformanceSummary = useMemo(
    () => buildFallbackPerformanceSummary(orders),
    [orders],
  )

  // The API summary is preferred ONLY if it actually carries data. In in-memory
  // mode the backend returns all-zeros even when the session has real fills,
  // which would pin headline values to $0 while Daily P&L showed a real loss.
  const apiSummaryHasSignal =
    performanceSummary != null &&
    ((performanceSummary.total_pnl ?? 0) !== 0 ||
      (performanceSummary.win_rate ?? 0) !== 0 ||
      (performanceSummary.best_trade ?? 0) !== 0 ||
      (performanceSummary.worst_trade ?? 0) !== 0)
  const resolvedPerformanceSummary = apiSummaryHasSignal
    ? performanceSummary
    : ((fallbackPerformanceSummary as typeof performanceSummary) ?? performanceSummary)

  const agents = useMemo(
    () => buildAgentSummaries(agentLogs, agentStatuses, agentInstances),
    [agentLogs, agentStatuses, agentInstances],
  )

  // Show the explicit "no agents" message only after a delay to avoid flashing
  // it during a normal connection bootstrap.
  useEffect(() => {
    if (!wsConnected || agents.length > 0) {
      setShowNoAgentDataMessage(false)
      return
    }
    const timer = setTimeout(() => {
      const state = useCodexStore.getState()
      const hasAgentData =
        state.agentLogs.length > 0 ||
        state.agentStatuses.length > 0 ||
        state.agentInstances.length > 0
      if (!hasAgentData && state.wsConnected) {
        setShowNoAgentDataMessage(true)
      }
    }, NO_AGENT_DATA_DELAY_MS)
    return () => clearTimeout(timer)
  }, [agents.length, wsConnected])

  const learningSummary = useMemo(
    () =>
      buildLearningSummary(
        streamStats,
        learningEvents,
        data.gradeHistory,
        data.icWeights,
        proposals,
        orders,
      ),
    [streamStats, learningEvents, data.gradeHistory, data.icWeights, proposals, orders],
  )

  const cleanGradeHistory = useMemo(
    () => buildCleanGradeHistory(data.gradeHistory),
    [data.gradeHistory],
  )

  const pipelineStages = useMemo(
    () =>
      buildPipelineStages(
        tradeFeed,
        cleanGradeHistory,
        learningSummary.reflectionsCompleted,
        learningSummary.icValuesUpdated,
        proposals,
        streamStats,
      ),
    [tradeFeed, cleanGradeHistory, learningSummary, proposals, streamStats],
  )

  const wiringFreshness = useMemo(
    () => buildWiringFreshness(agentStatuses, agentInstances, agentLogs),
    [agentStatuses, agentInstances, agentLogs],
  )

  const tradeAgg = useMemo(() => buildTradeFeedAggregates(tradeFeed), [tradeFeed])
  const unrealizedPnl = useMemo(
    () => positions.reduce((sum, row) => sum + (toFiniteNumber((row as Record<string, unknown>).pnl) ?? 0), 0),
    [positions],
  )

  // ── System-section derived values ────────────────────────────────────────
  const latestTickTs = streamStats['market_ticks']?.lastMessageTimestamp ?? null
  const dataLatencyMs = latestTickTs ? Math.max(Date.now() - new Date(latestTickTs).getTime(), 0) : null
  const wsLatencyMs = wsLastMessageTimestamp
    ? Math.max(Date.now() - new Date(wsLastMessageTimestamp).getTime(), 0)
    : null
  const recentEventLatencyMs =
    recentEvents.length > 0 && recentEvents[0]?.timestamp
      ? Math.max(Date.now() - new Date(recentEvents[0].timestamp).getTime(), 0)
      : null
  const effectiveLatencyMs = dataLatencyMs ?? wsLatencyMs ?? recentEventLatencyMs
  const throughput = Number(wsDiagnostics?.messageRate ?? 0)
  const pipelineStatus: 'Healthy' | 'Degraded' | 'Stalled' = !latestTickTs
    ? 'Stalled'
    : dataLatencyMs != null && dataLatencyMs < PIPELINE_HEALTHY_LATENCY_MS
      ? 'Healthy'
      : 'Degraded'
  const signalsCount = streamStats['signals']?.count ?? 0
  const ordersCount = streamStats['orders']?.count ?? 0
  const executionsCount = streamStats['executions']?.count ?? 0
  const pipelineWarning = signalsCount > 0 && ordersCount === 0
  const hasMarketData = Boolean(
    latestTickTs ||
      (streamStats['market_ticks']?.count ?? 0) > 0 ||
      recentEvents.some((e) => e.stream === 'market_ticks' || e.stream === 'market_events'),
  )
  const isInMemoryMode = String((dashboardData as Record<string, unknown> | null)?.mode ?? '').includes('in_memory')
  const persistenceEnabled = Boolean(
    isInMemoryMode ||
      data.persistedCounts.length > 0 ||
      data.persistedEvents.length > 0 ||
      data.persistedLogs.length > 0 ||
      data.apiHealth.eventHistory === 'ok',
  )
  const signalAgentRealtimeCount =
    agentStatuses.find((a) => canonicalAgentKey(a.name) === 'SIGNAL_AGENT')?.event_count ?? 0
  const reasoningAgentStatus =
    agentStatuses.find((a) => canonicalAgentKey(a.name) === 'REASONING_AGENT')?.status ?? 'unknown'
  const executionAgentStatus =
    agentStatuses.find((a) => canonicalAgentKey(a.name) === 'EXECUTION_ENGINE')?.status ?? 'unknown'

  const pricesLoading = !data.pricesFetched && Object.keys(prices).length === 0
  const systemTone = toneForSystemStatus(systemStatus)

  return (
    <div className="min-h-screen bg-slate-100 pb-20 dark:bg-slate-950 lg:pb-4">
      <main className="mx-auto max-w-7xl space-y-4 px-4 py-5">
        <div
          className={cn(
            'border px-3 py-2 text-xs font-mono font-semibold uppercase tracking-widest',
            UI_RADIUS.card,
            TONE_CLASSES[systemTone].card,
            TONE_CLASSES[systemTone].text,
          )}
        >
          System Status: {systemStatus}
        </div>

        {section === 'overview' && (
          <OverviewSection
            summary={summary}
            performanceSummary={resolvedPerformanceSummary ?? null}
            orders={orders}
            agents={agents}
            prices={prices}
            pricesLoading={pricesLoading}
            wsConnected={wsConnected}
          />
        )}

        {section === 'trading' && (
          <TradingSection
            trades={tradeFeed}
            agentLogs={agentLogs}
            positions={positions}
            onTraceClick={setActiveTraceId}
          />
        )}

        {section === 'agents' && (
          <AgentsSection
            marketTickCount={marketTickCount}
            lastMarketSymbol={lastMarketSymbol}
            agents={agents}
            agentLogs={agentLogs}
            notifications={notifications}
            isInMemoryMode={isInMemoryMode}
            agentStatuses={agentStatuses}
            agentInstances={agentInstances}
            wiringFreshness={wiringFreshness}
            apiHealth={data.apiHealth}
            showNoAgentDataMessage={showNoAgentDataMessage}
            wsConnected={wsConnected}
          />
        )}

        {section === 'learning' && (
          <LearningSection
            pipelineStages={pipelineStages}
            learningSummary={learningSummary}
            proposals={proposals}
            onUpdateProposalStatus={updateProposalStatus}
            icWeights={data.icWeights}
            gradeHistory={cleanGradeHistory}
            resolvedPerformanceSummary={resolvedPerformanceSummary ?? null}
            summary={summary}
            agents={agents}
          />
        )}

        {section === 'system' && (
          <SystemSection
            effectiveLatencyMs={effectiveLatencyMs}
            throughput={throughput}
            pipelineStatus={pipelineStatus}
            pipelineWarning={pipelineWarning}
            hasMarketData={hasMarketData}
            latestTickTs={latestTickTs}
            systemFeedError={data.systemFeedError}
            persistenceEnabled={persistenceEnabled}
            isInMemoryMode={isInMemoryMode}
            llmAvailable={data.llmAvailable}
            llmProvider={data.llmProvider}
            wsConnected={wsConnected}
            prices={prices}
            pricesFetched={data.pricesFetched}
            wsDiagnostics={wsDiagnostics}
            wsMessageCount={wsMessageCount}
            wsLastMessageTimestamp={wsLastMessageTimestamp}
            realizedPnl={tradeAgg.realizedPnl}
            unrealizedPnl={unrealizedPnl}
            resolvedPerformanceSummary={resolvedPerformanceSummary ?? null}
            totalTrades={tradeAgg.totalTrades}
            pnlWinRate={tradeAgg.pnlWinRate}
            signalsCount={signalsCount}
            ordersCount={ordersCount}
            executionsCount={executionsCount}
            signalAgentRealtimeCount={signalAgentRealtimeCount}
            reasoningAgentStatus={reasoningAgentStatus}
            executionAgentStatus={executionAgentStatus}
            streamStats={streamStats}
            recentEvents={recentEvents}
            agentStatuses={agentStatuses}
            persistedCounts={data.persistedCounts}
            persistedEvents={data.persistedEvents}
            persistedLogs={data.persistedLogs}
            onTraceClick={setActiveTraceId}
          />
        )}
      </main>

      {activeTraceId ? (
        <TraceModal traceId={activeTraceId} onClose={() => setActiveTraceId(null)} />
      ) : null}
    </div>
  )
}
