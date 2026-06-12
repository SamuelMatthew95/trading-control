'use client'

import { useMemo } from 'react'

import { cn } from '@/lib/utils'
import {
  formatPercent,
  formatTimestamp,
  signedUSD,
  toFiniteNum as toFiniteNumber,
} from '@/lib/formatters'
import { consoleHeaderClass, consolePanelClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { PROPOSAL_APPROVED, PROPOSAL_REJECTED } from '@/constants/trading'
import { computePipeline } from './helpers'
import type { SystemDashboardProps } from './types'

import {
  TRACE_COLUMNS,
  deriveAgentActivity,
  deriveDecisionFeed,
  formatAge,
  formatClock,
  proposalLabel,
  resolveHealthTone,
  startOfUtcDayMs,
  timestampMs,
} from './derive'
import {
  KpiStrip,
  LABEL_CLASS,
  StatePill,
  type HealthIndicator,
  actionClass,
  statusToneClass,
} from './primitives'

const COPY = UI_COPY.system

export function SystemDashboard(props: SystemDashboardProps) {
  const pipeline = useMemo(
    () =>
      computePipeline({
        streamStats: props.streamStats,
        recentEvents: props.recentEvents,
        wsLastMessageTimestamp: props.wsLastMessageTimestamp,
        wsMessageRate: props.wsDiagnostics.messageRate,
      }),
    [props.streamStats, props.recentEvents, props.wsLastMessageTimestamp, props.wsDiagnostics.messageRate],
  )

  const decisionFeed = useMemo(
    () =>
      deriveDecisionFeed({
        agentLogs: props.agentLogs,
        notifications: props.notifications,
        orders: props.orders,
      }),
    [props.agentLogs, props.notifications, props.orders],
  )

  const agentActivity = useMemo(
    () =>
      deriveAgentActivity({
        agentStatuses: props.agentStatuses,
        agentLogs: props.agentLogs,
      }),
    [props.agentStatuses, props.agentLogs],
  )

  const selectedDecision = decisionFeed[0] ?? null
  const netPnl =
    props.resolvedPerformanceSummary?.total_pnl ??
    props.orders.reduce((sum, order) => sum + (toFiniteNumber(order.pnl) ?? 0), 0)
  const dayStartMs = startOfUtcDayMs(Date.now())
  const dailyPnl = props.orders.reduce((sum, order) => {
    const orderMs = timestampMs(order.timestamp ?? order.filled_at ?? order.created_at)
    if (orderMs < dayStartMs) return sum
    return sum + (toFiniteNumber(order.pnl) ?? 0)
  }, 0)
  const openExposure = props.positions.reduce((sum, position) => {
    const quantity = Math.abs(toFiniteNumber(position.quantity) ?? 0)
    const price =
      toFiniteNumber(position.current_price) ?? toFiniteNumber(position.entry_price) ?? 0
    return sum + quantity * price
  }, 0)
  const activePositions = props.positions.filter(
    (position) => position.side === 'long' || position.side === 'short',
  ).length
  const recentRiskAlert = props.riskAlerts[0]
  const riskState = recentRiskAlert
    ? String(recentRiskAlert.severity ?? recentRiskAlert.status ?? COPY.review)
    : pipeline.pipelineStatus === 'Healthy'
      ? COPY.acceptable
      : COPY.review

  // Dashboard read-path health: a `/dashboard/state` failure surfaces as
  // systemFeedError / apiHealth.dashboardState='error'. Surface it explicitly so
  // an outage is not masked by otherwise-generic indicators.
  const dashboardApiDown =
    Boolean(props.systemFeedError) || props.apiHealth.dashboardState === 'error'

  const healthIndicators: HealthIndicator[] = [
    {
      label: COPY.killSwitch,
      tone: props.killSwitchActive ? 'err' : 'ok',
      value: props.killSwitchActive ? COPY.engaged : COPY.clear,
    },
    {
      label: COPY.tradingEnabled,
      tone: props.killSwitchActive ? 'err' : 'ok',
      value: props.killSwitchActive ? COPY.disabled : COPY.enabled,
    },
    {
      label: COPY.marketOpen,
      tone: pipeline.hasMarketData ? 'ok' : 'warn',
      value: pipeline.hasMarketData ? COPY.streaming : COPY.noTicks,
    },
    {
      label: COPY.dataHealth,
      tone:
        pipeline.pipelineStatus === 'Healthy'
          ? 'ok'
          : pipeline.pipelineStatus === 'Degraded'
            ? 'warn'
            : 'err',
      value: pipeline.pipelineStatus,
    },
    {
      label: COPY.llmHealth,
      tone: props.llmAvailable === false ? 'warn' : props.llmAvailable === true ? 'ok' : 'neutral',
      value: props.llmAvailable === false ? COPY.llmFallback : props.llmProvider || COPY.unknown,
    },
  ]

  const systemHealth: HealthIndicator[] = [
    {
      label: COPY.healthMarketData,
      tone: pipeline.hasMarketData ? 'ok' : 'warn',
      value: `${pipeline.marketStageCount} ${COPY.healthTicks}`,
    },
    {
      label: COPY.healthWebSocket,
      tone: props.wsConnected ? 'ok' : 'err',
      value: props.wsConnected ? `${props.wsMessageCount} ${COPY.healthMsgs}` : COPY.healthDisconnected,
    },
    {
      label: COPY.healthDashboardApi,
      tone: dashboardApiDown ? 'err' : props.apiHealth.dashboardState === 'ok' ? 'ok' : 'warn',
      value: dashboardApiDown
        ? COPY.healthUnreachable
        : props.apiHealth.dashboardState === 'ok'
          ? COPY.healthLive
          : props.apiHealth.dashboardState,
    },
    {
      label: COPY.healthBroker,
      tone: props.streamStats.orders?.count ? 'ok' : 'neutral',
      value: `${props.streamStats.orders?.count ?? 0} ${COPY.healthOrders}`,
    },
    {
      label: COPY.healthDatabase,
      tone: props.isInMemoryMode ? 'warn' : props.apiHealth.eventHistory === 'ok' ? 'ok' : 'err',
      value: props.isInMemoryMode ? COPY.healthMemory : props.apiHealth.eventHistory,
    },
    {
      label: COPY.healthRedis,
      tone: props.wsConnected ? 'ok' : 'warn',
      value: props.wsConnected ? COPY.healthEventBus : COPY.healthNoStream,
    },
    {
      label: COPY.healthLlm,
      tone: props.llmAvailable === false ? 'warn' : props.llmAvailable === true ? 'ok' : 'neutral',
      value: props.llmProvider || COPY.unknown,
    },
  ]

  const approvedProposals = props.proposals.filter((proposal) => proposal.status === PROPOSAL_APPROVED)
  const rejectedProposals = props.proposals.filter((proposal) => proposal.status === PROPOSAL_REJECTED)
  const proposalSuccessRate =
    props.proposals.length > 0 ? approvedProposals.length / props.proposals.length : null

  return (
    <div className="space-y-3 text-foreground">
      {dashboardApiDown && (
        <div
          className="flex items-center gap-2 rounded-xl border border-danger/40 bg-danger/10 px-3 py-2 text-xs font-semibold text-danger"
          role="alert"
        >
          <span className="h-2 w-2 rounded-full bg-danger" aria-hidden="true" />
          <span>
            {COPY.apiDownPrefix}
            {props.systemFeedError ? ` — ${props.systemFeedError}` : ''}
            {COPY.apiDownSuffix}
          </span>
        </div>
      )}
      <section
        className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_360px]"
        aria-label="Command Center overview"
      >
        {/* self-start: size this card to its single KPI row instead of letting
            the grid stretch it to match the taller Operator Controls panel,
            which left a large empty band of card below the metrics. */}
        <div className={cn(consolePanelClass, 'self-start')}>
          <div className={consoleHeaderClass}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className={sectionTitleClass}>{COPY.commandCenter}</p>
                <h1 className="mt-1 text-xl font-semibold tracking-tight text-foreground">
                  {COPY.headline}
                </h1>
              </div>
              <span className="rounded-full border border-strong px-2 py-1 font-mono text-3xs uppercase tracking-caps text-muted-foreground">
                {props.isInMemoryMode ? COPY.modePaper : COPY.modeLive}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-2 divide-x divide-y md:grid-cols-3 xl:grid-cols-6 xl:divide-y-0">
            <KpiStrip label={COPY.kpiNetPnl} value={signedUSD(netPnl)} tone={netPnl >= 0 ? 'ok' : 'err'} />
            <KpiStrip label={COPY.kpiDailyPnl} value={signedUSD(dailyPnl)} tone={dailyPnl >= 0 ? 'ok' : 'err'} />
            <KpiStrip label={COPY.kpiOpenExposure} value={signedUSD(openExposure)} />
            <KpiStrip label={COPY.kpiActivePositions} value={String(activePositions)} />
            <KpiStrip label={COPY.kpiRegime} value={props.regime || COPY.unknown} />
            <KpiStrip
              label={COPY.kpiRiskState}
              value={riskState}
              tone={riskState.toLowerCase().includes('acceptable') ? 'ok' : 'warn'}
            />
          </div>
        </div>
        <div className={consolePanelClass} aria-label="Operational controls">
          <div className={consoleHeaderClass}>
            <p className={sectionTitleClass}>{COPY.operatorControls}</p>
          </div>
          <div>
            {healthIndicators.map((indicator) => (
              <StatePill key={indicator.label} {...indicator} />
            ))}
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.15fr)_minmax(420px,0.85fr)]">
        <div className={consolePanelClass}>
          <div className={cn(consoleHeaderClass, 'flex items-center justify-between gap-2')}>
            <p className={sectionTitleClass}>{COPY.decisionFeed}</p>
            <span className="font-mono text-3xs uppercase tracking-caps text-muted-foreground">
              {COPY.windowed} {decisionFeed.length}
            </span>
          </div>
          <div className="max-h-[520px] overflow-y-auto" role="feed" aria-label={COPY.feedAria}>
            {decisionFeed.length === 0 ? (
              <div className="px-3 py-8 text-sm text-muted-foreground">{COPY.feedEmpty}</div>
            ) : (
              decisionFeed.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => props.setActiveTraceId(item.traceId)}
                  disabled={!item.traceId}
                  className="grid w-full grid-cols-[72px_1fr] gap-3 border-b px-3 py-2 text-left transition hover:bg-muted/50 disabled:cursor-default disabled:hover:bg-transparent"
                >
                  <time className="font-mono text-2xs tabular-nums text-muted-foreground">
                    {formatClock(item.timestamp)}
                  </time>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          'rounded px-1.5 py-0.5 font-mono text-xs font-semibold ring-1',
                          actionClass(item.action),
                        )}
                      >
                        {item.action}
                      </span>
                      <span className="font-mono text-sm font-semibold text-foreground">{item.symbol}</span>
                      {item.confidence != null && (
                        <span className="font-mono text-xs text-muted-foreground">
                          {COPY.confidence} {formatPercent(item.confidence)}
                        </span>
                      )}
                      <span className="ml-auto font-mono text-3xs uppercase tracking-caps text-muted-foreground/70">
                        {item.source}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      <span className="text-muted-foreground/70">{COPY.reason}</span>
                      <ul className="mt-1 grid gap-0.5 sm:grid-cols-2">
                        {item.reason.map((reason) => (
                          <li key={reason} className="truncate">
                            - {reason}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        <div className={consolePanelClass}>
          <div className={consoleHeaderClass}>
            <p className={sectionTitleClass}>{COPY.traceExplorer}</p>
          </div>
          <div className="p-3">
            {selectedDecision ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/40 px-3 py-2">
                  <div>
                    <p className="font-mono text-sm text-foreground">
                      {selectedDecision.action} {selectedDecision.symbol}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {COPY.tracePrefix} {selectedDecision.traceId ?? COPY.traceNotAttached}
                    </p>
                  </div>
                  <span className="font-mono text-xs text-muted-foreground">
                    {formatTimestamp(selectedDecision.timestamp)}
                  </span>
                </div>
                <div className="space-y-1">
                  {TRACE_COLUMNS.map((label, index) => (
                    <details
                      key={label}
                      className="group rounded-lg border bg-card open:bg-muted/40"
                      open={index < 3}
                    >
                      <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-xs font-semibold text-foreground/80 marker:hidden">
                        <span className="flex h-5 w-5 items-center justify-center rounded-full border border-strong font-mono text-3xs text-muted-foreground">
                          {index + 1}
                        </span>
                        {label}
                        <span className="ml-auto text-muted-foreground/70 group-open:hidden">
                          {COPY.expand}
                        </span>
                      </summary>
                      <div className="border-t px-3 py-2 text-xs leading-5 text-muted-foreground">
                        {index === 0 && selectedDecision.reason[0]}
                        {index === 1 && selectedDecision.reason.join(' ')}
                        {index === 2 && riskState}
                        {index === 3 &&
                          `${activePositions} ${COPY.activePositionsOf} ${signedUSD(openExposure)} ${COPY.exposure}`}
                        {index === 4 &&
                          `${selectedDecision.source} ${COPY.eventAt} ${formatClock(selectedDecision.timestamp)}`}
                        {index === 5 &&
                          (selectedDecision.action === 'SKIP' ? COPY.noOrderRouted : COPY.awaitingGrade)}
                      </div>
                    </details>
                  ))}
                </div>
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-strong px-3 py-8 text-sm text-muted-foreground">
                {COPY.noTraceSelected}
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 xl:grid-cols-3">
        <div className={consolePanelClass}>
          <div className={consoleHeaderClass}>
            <p className={sectionTitleClass}>{COPY.cognitiveEvolution}</p>
          </div>
          <div className="divide-y">
            <KpiStrip
              label={COPY.strategyVersion}
              value={`v${Math.max(1, approvedProposals.length + rejectedProposals.length + 1)}`}
            />
            <KpiStrip
              label={COPY.lastApproved}
              value={approvedProposals[0] ? proposalLabel(approvedProposals[0]) : COPY.noneApproved}
            />
            <KpiStrip
              label={COPY.proposalSuccessRate}
              value={proposalSuccessRate == null ? NO_DATA : formatPercent(proposalSuccessRate)}
            />
            <div className="px-3 py-2">
              <p className={LABEL_CLASS}>{COPY.configTimeline}</p>
              <ol className="mt-2 space-y-2">
                {(props.proposals.length > 0 ? props.proposals.slice(0, 4) : []).map((proposal) => (
                  <li key={proposal.id} className="border-l border-strong pl-3 text-xs text-muted-foreground">
                    <p className="font-medium text-foreground/80">{proposalLabel(proposal)}</p>
                    <p>
                      {proposal.status} {COPY.afterReview}
                    </p>
                  </li>
                ))}
                {props.proposals.length === 0 && (
                  <li className="text-xs text-muted-foreground">{COPY.noMutations}</li>
                )}
              </ol>
            </div>
          </div>
        </div>

        <div className={consolePanelClass}>
          <div className={consoleHeaderClass}>
            <p className={sectionTitleClass}>{COPY.agentActivity}</p>
          </div>
          <div className="max-h-[520px] divide-y overflow-y-auto">
            {agentActivity.map((agent) => {
              const tone = resolveHealthTone(agent.status?.status)
              const currentTask =
                agent.relatedLog?.event_type ??
                agent.status?.last_event ??
                agent.status?.status ??
                COPY.idle
              const lastOutput = agent.relatedLog?.message ?? agent.status?.last_event ?? COPY.noOutput
              const latencyMs = toFiniteNumber(agent.relatedLog?.latency_ms)
              return (
                <div key={agent.key} className="px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-foreground">{agent.label}</p>
                    <span className={cn('h-2 w-2 rounded-full ring-4', statusToneClass(tone))} />
                  </div>
                  <dl className="mt-2 grid grid-cols-[90px_1fr] gap-x-2 gap-y-1 text-xs">
                    <dt className="text-muted-foreground/70">{COPY.currentTask}</dt>
                    <dd className="truncate text-foreground/70">{currentTask}</dd>
                    <dt className="text-muted-foreground/70">{COPY.lastOutput}</dt>
                    <dd className="truncate text-muted-foreground">{lastOutput}</dd>
                    <dt className="text-muted-foreground/70">{COPY.lastSeen}</dt>
                    <dd className="font-mono text-muted-foreground">
                      {formatAge(agent.status?.seconds_ago)}
                      {latencyMs != null ? ` · ${latencyMs.toFixed(0)}ms` : ''}
                    </dd>
                  </dl>
                </div>
              )
            })}
          </div>
        </div>

        <div className={consolePanelClass}>
          <div className={consoleHeaderClass}>
            <p className={sectionTitleClass}>{COPY.systemHealth}</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-1">
            {systemHealth.map((indicator) => (
              <StatePill key={indicator.label} {...indicator} />
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
