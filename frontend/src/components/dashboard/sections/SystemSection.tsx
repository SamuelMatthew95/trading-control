'use client'

import { Brain } from 'lucide-react'
import {
  TerminalCard,
  SectionHeader,
  EmptyState,
  StateIndicator,
  TerminalTable,
  TerminalRow,
  TerminalCell,
} from '@/components/terminal'
import { LearningDashboard } from '@/components/dashboard/LearningDashboard'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, type Tone } from '@/lib/state'
import { formatCurrency, formatDuration, formatPercent, formatTimestamp } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import type {
  AgentStatus as StoreAgentStatus,
  PerformanceSummary,
  PriceData,
  RecentEvent,
  WsDiagnostics,
} from '@/stores/useCodexStore'
import type { PersistedHistoryItem, PersistedStreamCount } from '@/lib/types'

type PipelineStatus = 'Healthy' | 'Degraded' | 'Stalled'

const PIPELINE_TONE: Record<PipelineStatus, Tone> = {
  Healthy: 'pos',
  Degraded: 'warn',
  Stalled: 'neg',
}

interface SystemSectionProps {
  // health
  effectiveLatencyMs: number | null
  throughput: number
  pipelineStatus: PipelineStatus
  pipelineWarning: boolean
  hasMarketData: boolean
  latestTickTs: string | null
  systemFeedError: string | null
  persistenceEnabled: boolean
  isInMemoryMode: boolean
  llmAvailable: boolean | null
  llmProvider: string

  // diagnostics
  wsConnected: boolean
  prices: Record<string, PriceData>
  pricesFetched: boolean
  wsDiagnostics: WsDiagnostics
  wsMessageCount: number
  wsLastMessageTimestamp: string | null

  // pnl clarity
  realizedPnl: number
  unrealizedPnl: number
  resolvedPerformanceSummary: PerformanceSummary | null
  totalTrades: number
  pnlWinRate: number

  // pipeline counts
  signalsCount: number
  ordersCount: number
  executionsCount: number
  signalAgentRealtimeCount: number
  reasoningAgentStatus: string
  executionAgentStatus: string
  streamStats: Record<string, { count: number; lastMessageTimestamp: string | null }>

  // recent events
  recentEvents: RecentEvent[]
  agentStatuses: StoreAgentStatus[]

  // persisted history
  persistedCounts: PersistedStreamCount[]
  persistedEvents: PersistedHistoryItem[]
  persistedLogs: PersistedHistoryItem[]

  onTraceClick: (traceId: string) => void
}

export function SystemSection(props: SystemSectionProps) {
  return (
    <div className="space-y-4">
      <SystemHealthPanel
        effectiveLatencyMs={props.effectiveLatencyMs}
        throughput={props.throughput}
        pipelineStatus={props.pipelineStatus}
      />

      <SystemBanners
        pipelineWarning={props.pipelineWarning}
        hasMarketData={props.hasMarketData}
        latestTickTs={props.latestTickTs}
        systemFeedError={props.systemFeedError}
        persistenceEnabled={props.persistenceEnabled}
        llmAvailable={props.llmAvailable}
        llmProvider={props.llmProvider}
      />

      <ConnectionDiagnosticsPanel
        wsConnected={props.wsConnected}
        prices={props.prices}
        pricesFetched={props.pricesFetched}
        wsDiagnostics={props.wsDiagnostics}
      />

      <LearningDashboard />

      <PnlClarityPanel
        realizedPnl={props.realizedPnl}
        unrealizedPnl={props.unrealizedPnl}
        totalDb={props.resolvedPerformanceSummary?.total_pnl ?? null}
        totalTrades={props.totalTrades}
        pnlWinRate={props.pnlWinRate}
      />

      <PipelineHandoffPanel
        signalsCount={props.signalsCount}
        ordersCount={props.ordersCount}
        executionsCount={props.executionsCount}
        signalAgentRealtimeCount={props.signalAgentRealtimeCount}
        reasoningAgentStatus={props.reasoningAgentStatus}
        executionAgentStatus={props.executionAgentStatus}
      />

      <PipelineStreamStatusPanel streamStats={props.streamStats} />

      <WebSocketStatusPanel
        wsConnected={props.wsConnected}
        wsMessageCount={props.wsMessageCount}
        wsLastMessageTimestamp={props.wsLastMessageTimestamp}
      />

      <RecentEventsPanel events={props.recentEvents} wsConnected={props.wsConnected} />

      <AgentObservabilityPanel agents={props.agentStatuses} />

      <PersistedHistoryPanel
        counts={props.persistedCounts}
        events={props.persistedEvents}
        logs={props.persistedLogs}
        isInMemoryMode={props.isInMemoryMode}
        onTraceClick={props.onTraceClick}
      />
    </div>
  )
}

// ── Sub-panels ────────────────────────────────────────────────────────────

function SystemHealthPanel({
  effectiveLatencyMs,
  throughput,
  pipelineStatus,
}: {
  effectiveLatencyMs: number | null
  throughput: number
  pipelineStatus: PipelineStatus
}) {
  const tone = PIPELINE_TONE[pipelineStatus]
  return (
    <TerminalCard>
      <SectionHeader title="System Health" />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <Tile label="Data latency" value={`${formatDuration(effectiveLatencyMs)} (${effectiveLatencyMs ?? '—'}ms)`} />
        <Tile label="Events/sec throughput" value={throughput.toFixed(2)} />
        <Tile
          label="Pipeline status"
          value={pipelineStatus}
          valueClassName={cn('font-semibold', TONE_CLASSES[tone].text)}
        />
      </div>
    </TerminalCard>
  )
}

function SystemBanners(props: {
  pipelineWarning: boolean
  hasMarketData: boolean
  latestTickTs: string | null
  systemFeedError: string | null
  persistenceEnabled: boolean
  llmAvailable: boolean | null
  llmProvider: string
}) {
  const banners: Array<{ tone: Tone; message: string }> = []
  if (props.pipelineWarning) {
    banners.push({ tone: 'warn', message: 'Signals generated but no orders placed' })
  }
  if (!props.hasMarketData) {
    banners.push({ tone: 'neg', message: 'No market data received' })
  }
  if (props.hasMarketData && !props.latestTickTs) {
    banners.push({
      tone: 'warn',
      message: 'Market events are arriving via WebSocket, but market_ticks lag metrics are missing.',
    })
  }
  if (props.systemFeedError) {
    banners.push({ tone: 'neg', message: props.systemFeedError })
  }
  if (!props.persistenceEnabled) {
    banners.push({
      tone: 'warn',
      message: 'Persistence appears disabled (no persisted events/logs). Agents/Learning views may show incomplete history.',
    })
  }
  if (props.llmAvailable === false) {
    const provider = props.llmProvider
      ? props.llmProvider.charAt(0).toUpperCase() + props.llmProvider.slice(1)
      : 'LLM'
    const envName = props.llmProvider ? props.llmProvider.toUpperCase() + '_API_KEY' : 'an LLM API key'
    banners.push({
      tone: 'info',
      message: `Rule-based mode — no ${provider} API key configured. Reasoning decisions use signal direction only; set ${envName} to enable AI-powered analysis.`,
    })
  }
  if (banners.length === 0) return null
  return (
    <>
      {banners.map((b, i) => (
        <div
          key={i}
          className={cn('rounded-[6px] p-3 text-sm', TONE_CLASSES[b.tone].card, TONE_CLASSES[b.tone].text)}
        >
          {b.message}
        </div>
      ))}
    </>
  )
}

function ConnectionDiagnosticsPanel({
  wsConnected,
  prices,
  pricesFetched,
  wsDiagnostics,
}: {
  wsConnected: boolean
  prices: Record<string, PriceData>
  pricesFetched: boolean
  wsDiagnostics: WsDiagnostics
}) {
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? '/api (fallback)'
  const wsUrl = (() => {
    if (typeof window === 'undefined') return '—'
    if (process.env.NEXT_PUBLIC_WS_URL) {
      return (
        process.env.NEXT_PUBLIC_WS_URL.replace(/^https?:\/\//, 'wss://').replace(/\/$/, '') +
        '/ws/dashboard'
      )
    }
    if (process.env.NEXT_PUBLIC_API_URL) {
      return (
        process.env.NEXT_PUBLIC_API_URL.replace(/\/api\/?$/, '').replace(/^https?:\/\//, 'wss://') +
        '/ws/dashboard'
      )
    }
    return window.location.host + '/ws/dashboard (same-origin)'
  })()
  const priceCount = Object.keys(prices).length
  const priceTone: Tone = priceCount > 0 ? 'pos' : pricesFetched ? 'warn' : 'muted'
  const priceLabel =
    priceCount > 0 ? `● ${priceCount} symbols` : pricesFetched ? '● Fetched – poller offline?' : '● Waiting…'

  return (
    <TerminalCard>
      <SectionHeader title="Connection Diagnostics" />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div className="rounded-[6px] border border-slate-200 p-3 dark:border-slate-800">
          <p className={UI_TEXT.muted}>WebSocket</p>
          <p
            className={cn(
              'mt-1 text-sm font-semibold',
              wsConnected ? TONE_CLASSES.pos.text : TONE_CLASSES.neg.text,
            )}
          >
            {wsConnected ? '● Connected' : '● Disconnected'}
          </p>
          <p className="mt-1 break-all text-[10px] font-mono text-slate-400">{wsUrl}</p>
        </div>
        <Tile label="API Base" value={apiBase} valueClassName="text-xs font-mono break-all" />
        <Tile
          label="Prices / REST"
          value={priceLabel}
          valueClassName={cn('text-sm font-semibold', TONE_CLASSES[priceTone].text)}
        />
        <Tile label="Reconnect attempts" value={String(wsDiagnostics.reconnectAttempts)} />
        <Tile
          label="Message rate"
          value={`${Number.isFinite(wsDiagnostics.messageRate) ? wsDiagnostics.messageRate.toFixed(2) : '0.00'} /sec`}
        />
        <Tile label="Last error" value={wsDiagnostics.lastError ?? 'None'} valueClassName="text-xs font-mono" />
      </div>
    </TerminalCard>
  )
}

function PnlClarityPanel({
  realizedPnl,
  unrealizedPnl,
  totalDb,
  totalTrades,
  pnlWinRate,
}: {
  realizedPnl: number
  unrealizedPnl: number
  totalDb: number | null
  totalTrades: number
  pnlWinRate: number
}) {
  return (
    <TerminalCard>
      <SectionHeader title="PnL Clarity" />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
        <Tile label="Realized" value={formatCurrency(realizedPnl)} />
        <Tile label="Unrealized" value={formatCurrency(unrealizedPnl)} />
        <Tile label="Session" value={formatCurrency(realizedPnl + unrealizedPnl)} />
        <Tile label="Total (DB)" value={formatCurrency(totalDb)} />
        <Tile label="Trades" value={String(totalTrades)} />
        <Tile label="Win rate" value={formatPercent(pnlWinRate, 1)} />
      </div>
    </TerminalCard>
  )
}

function PipelineHandoffPanel({
  signalsCount,
  ordersCount,
  executionsCount,
  signalAgentRealtimeCount,
  reasoningAgentStatus,
  executionAgentStatus,
}: {
  signalsCount: number
  ordersCount: number
  executionsCount: number
  signalAgentRealtimeCount: number
  reasoningAgentStatus: string
  executionAgentStatus: string
}) {
  return (
    <TerminalCard>
      <SectionHeader title="Pipeline Handoff" />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
        <Tile label="Signals (stream)" value={String(signalsCount)} />
        <Tile label="Orders" value={String(ordersCount)} />
        <Tile label="Executions" value={String(executionsCount)} />
        <Tile label="Signal Agent (RT)" value={String(signalAgentRealtimeCount)} />
      </div>
      <p className={cn(UI_TEXT.muted, 'mt-2')}>
        Reasoning: <span className="font-mono">{reasoningAgentStatus}</span> → Execution:{' '}
        <span className="font-mono">{executionAgentStatus}</span>
      </p>
    </TerminalCard>
  )
}

function PipelineStreamStatusPanel({
  streamStats,
}: {
  streamStats: Record<string, { count: number; lastMessageTimestamp: string | null }>
}) {
  const streams = ['market_ticks', 'signals', 'orders', 'executions', 'agent_logs', 'risk_alerts', 'notifications'] as const
  return (
    <TerminalCard>
      <SectionHeader title="Pipeline Status" />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {streams.map((streamName) => {
          const stat = streamStats[streamName] ?? { count: 0, lastMessageTimestamp: null }
          const isLive = Boolean(
            stat.lastMessageTimestamp &&
              Date.now() - new Date(stat.lastMessageTimestamp).getTime() < 60_000,
          )
          return (
            <div
              key={streamName}
              className="rounded-[6px] border border-slate-200 p-3 dark:border-slate-800"
            >
              <div className="flex items-center justify-between">
                <p className={UI_TEXT.label}>{streamName}</p>
                <StateIndicator tone={isLive ? 'pos' : 'muted'} />
              </div>
              <p className={cn(UI_TEXT.numeric, 'mt-1 text-lg text-slate-900 dark:text-slate-100')}>
                {stat.count}
              </p>
            </div>
          )
        })}
      </div>
    </TerminalCard>
  )
}

function WebSocketStatusPanel({
  wsConnected,
  wsMessageCount,
  wsLastMessageTimestamp,
}: {
  wsConnected: boolean
  wsMessageCount: number
  wsLastMessageTimestamp: string | null
}) {
  return (
    <TerminalCard>
      <SectionHeader title="WebSocket Status" />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <Tile
          label="Connection"
          value={wsConnected ? 'Connected' : 'Disconnected'}
          valueClassName={cn('text-sm font-semibold', wsConnected ? TONE_CLASSES.pos.text : 'text-slate-500')}
        />
        <Tile label="Messages Received" value={String(wsMessageCount)} />
        <Tile label="Last Message" value={formatTimestamp(wsLastMessageTimestamp)} />
      </div>
    </TerminalCard>
  )
}

function RecentEventsPanel({
  events,
  wsConnected,
}: {
  events: RecentEvent[]
  wsConnected: boolean
}) {
  return (
    <TerminalCard>
      <SectionHeader title="Recent Events" />
      {events.length === 0 ? (
        <EmptyState message={wsConnected ? 'No websocket events yet' : 'Stream disconnected'} />
      ) : (
        <div className="space-y-2">
          {events.map((event, index) => {
            const tone: Tone =
              event.stream === 'market_ticks'
                ? 'pos'
                : event.stream === 'signals'
                  ? 'info'
                  : event.stream === 'orders'
                    ? 'warn'
                    : 'muted'
            return (
              <div
                key={`${event.stream ?? 'evt'}-${event.timestamp ?? ''}-${event.msgId !== 'n/a' ? (event.msgId ?? index) : index}`}
                className="flex items-center justify-between rounded-[6px] border border-slate-200 px-3 py-2 dark:border-slate-800"
              >
                <span className={cn('rounded-[4px] px-2 py-0.5 text-xs font-semibold', TONE_CLASSES[tone].soft)}>
                  {event.stream}
                </span>
                <span className="text-xs font-mono text-slate-500">
                  {event.msgId !== 'n/a' ? event.msgId.slice(0, 10) : '—'}
                </span>
                <span className="text-xs font-mono text-slate-500">{formatTimestamp(event.timestamp)}</span>
              </div>
            )
          })}
        </div>
      )}
    </TerminalCard>
  )
}

function AgentObservabilityPanel({ agents }: { agents: StoreAgentStatus[] }) {
  return (
    <TerminalCard padded>
      <SectionHeader title="Agent Observability" />
      {agents.length === 0 ? (
        <EmptyState message="No agent status yet" icon={Brain} />
      ) : (
        <TerminalTable headers={['Agent', 'Status', 'Signals', 'Last action']}>
          {agents.map((agent) => (
            <TerminalRow key={agent.name}>
              <TerminalCell className="font-semibold">{agent.name}</TerminalCell>
              <TerminalCell>{agent.status}</TerminalCell>
              <TerminalCell numeric>{agent.event_count}</TerminalCell>
              <TerminalCell>{agent.last_event || '—'}</TerminalCell>
            </TerminalRow>
          ))}
        </TerminalTable>
      )}
    </TerminalCard>
  )
}

function PersistedHistoryPanel({
  counts,
  events,
  logs,
  isInMemoryMode,
  onTraceClick,
}: {
  counts: PersistedStreamCount[]
  events: PersistedHistoryItem[]
  logs: PersistedHistoryItem[]
  isInMemoryMode: boolean
  onTraceClick: (traceId: string) => void
}) {
  const emptyMessage = isInMemoryMode
    ? 'In-memory mode (no DB persistence)'
    : 'Persistence not enabled'

  return (
    <TerminalCard>
      <SectionHeader title="Persisted Event History" />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div className="rounded-[6px] border border-slate-200 p-3 dark:border-slate-800">
          <p className={cn(UI_TEXT.muted, 'mb-2')}>Processed counts by stream</p>
          {counts.length === 0 ? (
            <p className={UI_TEXT.muted}>{emptyMessage}</p>
          ) : (
            <div className="space-y-1">
              {counts.slice(0, 8).map((row) => (
                <div key={row.stream} className="flex items-center justify-between text-xs font-mono">
                  <span className="text-slate-600 dark:text-slate-300">{row.stream}</span>
                  <span className="text-slate-900 dark:text-slate-100">{row.processed_count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="rounded-[6px] border border-slate-200 p-3 dark:border-slate-800">
          <p className={cn(UI_TEXT.muted, 'mb-2')}>Latest persisted events</p>
          {events.length === 0 ? (
            <p className={UI_TEXT.muted}>{emptyMessage}</p>
          ) : (
            <div className="space-y-1">
              {events.slice(0, 8).map((evt) => (
                <div key={evt.id} className="flex items-center justify-between text-xs font-mono">
                  <span className="text-slate-600 dark:text-slate-300">{evt.kind}</span>
                  <span className="text-slate-500">{formatTimestamp(evt.created_at)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="mt-3 rounded-[6px] border border-slate-200 p-3 dark:border-slate-800">
        <p className={cn(UI_TEXT.muted, 'mb-2')}>Latest persisted agent logs</p>
        {logs.length === 0 ? (
          <p className={UI_TEXT.muted}>{emptyMessage}</p>
        ) : (
          <div className="space-y-1">
            {logs.slice(0, 10).map((log) => (
              <button
                key={log.id}
                type="button"
                onClick={() => log.trace_id && onTraceClick(log.trace_id)}
                className="flex w-full items-center justify-between rounded-[4px] px-1 py-1 text-left text-xs font-mono hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <span className="text-slate-600 dark:text-slate-300">{log.kind}</span>
                <span className="text-slate-500">{formatTimestamp(log.created_at)}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </TerminalCard>
  )
}

// ── Tile primitive ─────────────────────────────────────────────────────────

function Tile({
  label,
  value,
  valueClassName,
}: {
  label: string
  value: string
  valueClassName?: string
}) {
  return (
    <div className="rounded-[6px] border border-slate-200 p-3 dark:border-slate-800">
      <p className={UI_TEXT.muted}>{label}</p>
      <p className={cn('text-sm font-mono', valueClassName ?? 'text-slate-900 dark:text-slate-100')}>{value}</p>
    </div>
  )
}
