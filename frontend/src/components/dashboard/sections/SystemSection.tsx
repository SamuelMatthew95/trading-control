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
import {
  formatCurrency,
  formatDuration,
  formatPercent,
  formatTimestamp,
} from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import {
  BANNER_BASE,
  CHIP_BASE,
  COMPACT_MONO_ROW,
  EVENT_ROW,
  INNER_TILE,
  LIST_HOVER_BUTTON,
  PIPELINE_STREAM_GRID,
  PRIMARY_TEXT,
  ROW_BETWEEN,
  SECONDARY_TEXT,
  STACK,
  STACK_TIGHT,
  SUB_PANEL_GRID,
  SUB_PANEL_GRID_2,
  SUB_PANEL_GRID_4,
  SUB_PANEL_GRID_6,
  TERTIARY_TEXT,
  URL_MONO,
} from '@/lib/styles'
import {
  PIPELINE_STREAM_NAMES,
  RECENT_EVENT_TONE,
  STREAM_LIVE_WINDOW_MS,
} from '@/lib/constants/learning'
import type {
  AgentStatus as StoreAgentStatus,
  PerformanceSummary,
  PriceData,
  RecentEvent,
  WsDiagnostics,
} from '@/stores/useCodexStore'
import type { PersistedHistoryItem, PersistedStreamCount } from '@/lib/types'

// ── Types ─────────────────────────────────────────────────────────────────

type PipelineStatus = 'Healthy' | 'Degraded' | 'Stalled'

const PIPELINE_TONE: Record<PipelineStatus, Tone> = {
  Healthy: 'pos',
  Degraded: 'warn',
  Stalled: 'neg',
}

interface StreamStat {
  count: number
  lastMessageTimestamp: string | null
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
  streamStats: Record<string, StreamStat>

  // recent events
  recentEvents: RecentEvent[]
  agentStatuses: StoreAgentStatus[]

  // persisted history
  persistedCounts: PersistedStreamCount[]
  persistedEvents: PersistedHistoryItem[]
  persistedLogs: PersistedHistoryItem[]

  onTraceClick: (traceId: string) => void
}

// ── Tile primitive (single source of truth for sub-panel cells) ───────────

interface TileProps {
  label: string
  value: string
  valueClassName?: string
}

function Tile(props: TileProps) {
  const valueClass = props.valueClassName ?? PRIMARY_TEXT
  return (
    <div className={INNER_TILE}>
      <p className={UI_TEXT.muted}>{props.label}</p>
      <p className={cn('text-sm font-mono', valueClass)}>{props.value}</p>
    </div>
  )
}

// ── Top-level orchestrator ────────────────────────────────────────────────

export function SystemSection(props: SystemSectionProps) {
  return (
    <div className={STACK}>
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

// ── Banner rendering ──────────────────────────────────────────────────────

interface BannerSpec {
  tone: Tone
  message: string
}

interface SystemBannersProps {
  pipelineWarning: boolean
  hasMarketData: boolean
  latestTickTs: string | null
  systemFeedError: string | null
  persistenceEnabled: boolean
  llmAvailable: boolean | null
  llmProvider: string
}

function llmBannerMessage(provider: string): string {
  const display = provider ? provider.charAt(0).toUpperCase() + provider.slice(1) : 'LLM'
  const envName = provider ? provider.toUpperCase() + '_API_KEY' : 'an LLM API key'
  return `Rule-based mode — no ${display} API key configured. Reasoning decisions use signal direction only; set ${envName} to enable AI-powered analysis.`
}

function buildBanners(props: SystemBannersProps): BannerSpec[] {
  const banners: BannerSpec[] = []
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
      message:
        'Persistence appears disabled (no persisted events/logs). Agents/Learning views may show incomplete history.',
    })
  }
  if (props.llmAvailable === false) {
    banners.push({ tone: 'info', message: llmBannerMessage(props.llmProvider) })
  }
  return banners
}

function Banner(props: { spec: BannerSpec }) {
  const { spec } = props
  return (
    <div className={cn(BANNER_BASE, TONE_CLASSES[spec.tone].card, TONE_CLASSES[spec.tone].text)}>
      {spec.message}
    </div>
  )
}

function SystemBanners(props: SystemBannersProps) {
  const banners = buildBanners(props)
  if (banners.length === 0) return null
  return (
    <>
      {banners.map((spec, i) => (
        <Banner key={`banner-${i}`} spec={spec} />
      ))}
    </>
  )
}

// ── Sub-panels ────────────────────────────────────────────────────────────

interface SystemHealthPanelProps {
  effectiveLatencyMs: number | null
  throughput: number
  pipelineStatus: PipelineStatus
}

function formatLatencyValue(ms: number | null): string {
  return `${formatDuration(ms)} (${ms ?? '—'}ms)`
}

function SystemHealthPanel(props: SystemHealthPanelProps) {
  const tone = PIPELINE_TONE[props.pipelineStatus]
  return (
    <TerminalCard>
      <SectionHeader title="System Health" />
      <div className={SUB_PANEL_GRID}>
        <Tile label="Data latency" value={formatLatencyValue(props.effectiveLatencyMs)} />
        <Tile label="Events/sec throughput" value={props.throughput.toFixed(2)} />
        <Tile
          label="Pipeline status"
          value={props.pipelineStatus}
          valueClassName={cn('font-semibold', TONE_CLASSES[tone].text)}
        />
      </div>
    </TerminalCard>
  )
}

interface ConnectionDiagnosticsPanelProps {
  wsConnected: boolean
  prices: Record<string, PriceData>
  pricesFetched: boolean
  wsDiagnostics: WsDiagnostics
}

function deriveWsUrl(): string {
  if (typeof window === 'undefined') return '—'
  const wsEnv = process.env.NEXT_PUBLIC_WS_URL
  if (wsEnv) {
    return wsEnv.replace(/^https?:\/\//, 'wss://').replace(/\/$/, '') + '/ws/dashboard'
  }
  const apiEnv = process.env.NEXT_PUBLIC_API_URL
  if (apiEnv) {
    return apiEnv.replace(/\/api\/?$/, '').replace(/^https?:\/\//, 'wss://') + '/ws/dashboard'
  }
  return window.location.host + '/ws/dashboard (same-origin)'
}

function priceStatus(priceCount: number, pricesFetched: boolean): { tone: Tone; label: string } {
  if (priceCount > 0) return { tone: 'pos', label: `● ${priceCount} symbols` }
  if (pricesFetched) return { tone: 'warn', label: '● Fetched – poller offline?' }
  return { tone: 'muted', label: '● Waiting…' }
}

function WebSocketTile(props: { wsConnected: boolean; wsUrl: string }) {
  return (
    <div className={INNER_TILE}>
      <p className={UI_TEXT.muted}>WebSocket</p>
      <p
        className={cn(
          'mt-1 text-sm font-semibold',
          props.wsConnected ? TONE_CLASSES.pos.text : TONE_CLASSES.neg.text,
        )}
      >
        {props.wsConnected ? '● Connected' : '● Disconnected'}
      </p>
      <p className={URL_MONO}>{props.wsUrl}</p>
    </div>
  )
}

function ConnectionDiagnosticsPanel(props: ConnectionDiagnosticsPanelProps) {
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? '/api (fallback)'
  const wsUrl = deriveWsUrl()
  const priceCount = Object.keys(props.prices).length
  const priceState = priceStatus(priceCount, props.pricesFetched)
  const messageRateText = `${
    Number.isFinite(props.wsDiagnostics.messageRate) ? props.wsDiagnostics.messageRate.toFixed(2) : '0.00'
  } /sec`

  return (
    <TerminalCard>
      <SectionHeader title="Connection Diagnostics" />
      <div className={SUB_PANEL_GRID}>
        <WebSocketTile wsConnected={props.wsConnected} wsUrl={wsUrl} />
        <Tile label="API Base" value={apiBase} valueClassName="text-xs font-mono break-all" />
        <Tile
          label="Prices / REST"
          value={priceState.label}
          valueClassName={cn('text-sm font-semibold', TONE_CLASSES[priceState.tone].text)}
        />
        <Tile label="Reconnect attempts" value={String(props.wsDiagnostics.reconnectAttempts)} />
        <Tile label="Message rate" value={messageRateText} />
        <Tile
          label="Last error"
          value={props.wsDiagnostics.lastError ?? 'None'}
          valueClassName="text-xs font-mono"
        />
      </div>
    </TerminalCard>
  )
}

interface PnlClarityPanelProps {
  realizedPnl: number
  unrealizedPnl: number
  totalDb: number | null
  totalTrades: number
  pnlWinRate: number
}

function PnlClarityPanel(props: PnlClarityPanelProps) {
  return (
    <TerminalCard>
      <SectionHeader title="PnL Clarity" />
      <div className={SUB_PANEL_GRID_6}>
        <Tile label="Realized" value={formatCurrency(props.realizedPnl)} />
        <Tile label="Unrealized" value={formatCurrency(props.unrealizedPnl)} />
        <Tile label="Session" value={formatCurrency(props.realizedPnl + props.unrealizedPnl)} />
        <Tile label="Total (DB)" value={formatCurrency(props.totalDb)} />
        <Tile label="Trades" value={String(props.totalTrades)} />
        <Tile label="Win rate" value={formatPercent(props.pnlWinRate, 1)} />
      </div>
    </TerminalCard>
  )
}

interface PipelineHandoffPanelProps {
  signalsCount: number
  ordersCount: number
  executionsCount: number
  signalAgentRealtimeCount: number
  reasoningAgentStatus: string
  executionAgentStatus: string
}

function PipelineHandoffPanel(props: PipelineHandoffPanelProps) {
  return (
    <TerminalCard>
      <SectionHeader title="Pipeline Handoff" />
      <div className={SUB_PANEL_GRID_4}>
        <Tile label="Signals (stream)" value={String(props.signalsCount)} />
        <Tile label="Orders" value={String(props.ordersCount)} />
        <Tile label="Executions" value={String(props.executionsCount)} />
        <Tile label="Signal Agent (RT)" value={String(props.signalAgentRealtimeCount)} />
      </div>
      <p className={cn(UI_TEXT.muted, 'mt-2')}>
        Reasoning: <span className={UI_TEXT.numeric}>{props.reasoningAgentStatus}</span> →
        Execution: <span className={UI_TEXT.numeric}>{props.executionAgentStatus}</span>
      </p>
    </TerminalCard>
  )
}

function isStreamLive(stat: StreamStat): boolean {
  if (!stat.lastMessageTimestamp) return false
  return Date.now() - new Date(stat.lastMessageTimestamp).getTime() < STREAM_LIVE_WINDOW_MS
}

function StreamStatTile(props: { name: string; stat: StreamStat }) {
  const live = isStreamLive(props.stat)
  return (
    <div className={INNER_TILE}>
      <div className={ROW_BETWEEN}>
        <p className={UI_TEXT.label}>{props.name}</p>
        <StateIndicator tone={live ? 'pos' : 'muted'} />
      </div>
      <p className={cn(UI_TEXT.numeric, 'mt-1 text-lg', PRIMARY_TEXT)}>{props.stat.count}</p>
    </div>
  )
}

function PipelineStreamStatusPanel(props: { streamStats: Record<string, StreamStat> }) {
  return (
    <TerminalCard>
      <SectionHeader title="Pipeline Status" />
      <div className={PIPELINE_STREAM_GRID}>
        {PIPELINE_STREAM_NAMES.map((name) => (
          <StreamStatTile
            key={name}
            name={name}
            stat={props.streamStats[name] ?? { count: 0, lastMessageTimestamp: null }}
          />
        ))}
      </div>
    </TerminalCard>
  )
}

interface WebSocketStatusPanelProps {
  wsConnected: boolean
  wsMessageCount: number
  wsLastMessageTimestamp: string | null
}

function WebSocketStatusPanel(props: WebSocketStatusPanelProps) {
  const connectionClass = cn(
    'text-sm font-semibold',
    props.wsConnected ? TONE_CLASSES.pos.text : 'text-slate-500',
  )
  return (
    <TerminalCard>
      <SectionHeader title="WebSocket Status" />
      <div className={SUB_PANEL_GRID}>
        <Tile
          label="Connection"
          value={props.wsConnected ? 'Connected' : 'Disconnected'}
          valueClassName={connectionClass}
        />
        <Tile label="Messages Received" value={String(props.wsMessageCount)} />
        <Tile label="Last Message" value={formatTimestamp(props.wsLastMessageTimestamp)} />
      </div>
    </TerminalCard>
  )
}

function recentEventTone(stream: string): Tone {
  return RECENT_EVENT_TONE[stream] ?? 'muted'
}

interface RecentEventRowProps {
  event: RecentEvent
  index: number
}

const RECENT_EVENT_LABEL = 'text-xs font-mono ' + TERTIARY_TEXT

function RecentEventRow(props: RecentEventRowProps) {
  const { event, index } = props
  const tone = recentEventTone(event.stream)
  const msgLabel = event.msgId !== 'n/a' ? event.msgId.slice(0, 10) : '—'
  const key = `${event.stream ?? 'evt'}-${event.timestamp ?? ''}-${
    event.msgId !== 'n/a' ? (event.msgId ?? index) : index
  }`
  return (
    <div key={key} className={EVENT_ROW}>
      <span className={cn(CHIP_BASE, TONE_CLASSES[tone].soft)}>{event.stream}</span>
      <span className={RECENT_EVENT_LABEL}>{msgLabel}</span>
      <span className={RECENT_EVENT_LABEL}>{formatTimestamp(event.timestamp)}</span>
    </div>
  )
}

function RecentEventsPanel(props: { events: RecentEvent[]; wsConnected: boolean }) {
  if (props.events.length === 0) {
    return (
      <TerminalCard>
        <SectionHeader title="Recent Events" />
        <EmptyState message={props.wsConnected ? 'No websocket events yet' : 'Stream disconnected'} />
      </TerminalCard>
    )
  }
  return (
    <TerminalCard>
      <SectionHeader title="Recent Events" />
      <div className={STACK_TIGHT}>
        {props.events.map((event, index) => (
          <RecentEventRow key={`${event.stream}-${index}`} event={event} index={index} />
        ))}
      </div>
    </TerminalCard>
  )
}

function AgentObservabilityRow(props: { agent: StoreAgentStatus }) {
  const { agent } = props
  return (
    <TerminalRow>
      <TerminalCell className="font-semibold">{agent.name}</TerminalCell>
      <TerminalCell>{agent.status}</TerminalCell>
      <TerminalCell numeric>{agent.event_count}</TerminalCell>
      <TerminalCell>{agent.last_event || '—'}</TerminalCell>
    </TerminalRow>
  )
}

function AgentObservabilityPanel(props: { agents: StoreAgentStatus[] }) {
  if (props.agents.length === 0) {
    return (
      <TerminalCard padded>
        <SectionHeader title="Agent Observability" />
        <EmptyState message="No agent status yet" icon={Brain} />
      </TerminalCard>
    )
  }
  return (
    <TerminalCard padded>
      <SectionHeader title="Agent Observability" />
      <TerminalTable headers={['Agent', 'Status', 'Signals', 'Last action']}>
        {props.agents.map((agent) => (
          <AgentObservabilityRow key={agent.name} agent={agent} />
        ))}
      </TerminalTable>
    </TerminalCard>
  )
}

interface PersistedHistoryPanelProps {
  counts: PersistedStreamCount[]
  events: PersistedHistoryItem[]
  logs: PersistedHistoryItem[]
  isInMemoryMode: boolean
  onTraceClick: (traceId: string) => void
}

function emptyPersistedMessage(isInMemoryMode: boolean): string {
  return isInMemoryMode ? 'In-memory mode (no DB persistence)' : 'Persistence not enabled'
}

const PERSISTED_HEADING = cn(UI_TEXT.muted, 'mb-2')
const PERSISTED_SECONDARY_LABEL = SECONDARY_TEXT
const PERSISTED_TERTIARY_LABEL = TERTIARY_TEXT

function PersistedCountsCard(props: { counts: PersistedStreamCount[]; emptyMessage: string }) {
  return (
    <div className={INNER_TILE}>
      <p className={PERSISTED_HEADING}>Processed counts by stream</p>
      {props.counts.length === 0 ? (
        <p className={UI_TEXT.muted}>{props.emptyMessage}</p>
      ) : (
        <div className="space-y-1">
          {props.counts.slice(0, 8).map((row) => (
            <PersistedCountRow key={row.stream} row={row} />
          ))}
        </div>
      )}
    </div>
  )
}

function PersistedCountRow(props: { row: PersistedStreamCount }) {
  return (
    <div className={COMPACT_MONO_ROW}>
      <span className={PERSISTED_SECONDARY_LABEL}>{props.row.stream}</span>
      <span className={PRIMARY_TEXT}>{props.row.processed_count}</span>
    </div>
  )
}

function PersistedEventsCard(props: { events: PersistedHistoryItem[]; emptyMessage: string }) {
  return (
    <div className={INNER_TILE}>
      <p className={PERSISTED_HEADING}>Latest persisted events</p>
      {props.events.length === 0 ? (
        <p className={UI_TEXT.muted}>{props.emptyMessage}</p>
      ) : (
        <div className="space-y-1">
          {props.events.slice(0, 8).map((evt) => (
            <PersistedEventRow key={evt.id} event={evt} />
          ))}
        </div>
      )}
    </div>
  )
}

function PersistedEventRow(props: { event: PersistedHistoryItem }) {
  return (
    <div className={COMPACT_MONO_ROW}>
      <span className={PERSISTED_SECONDARY_LABEL}>{props.event.kind}</span>
      <span className={PERSISTED_TERTIARY_LABEL}>{formatTimestamp(props.event.created_at)}</span>
    </div>
  )
}

function PersistedLogsCard(props: {
  logs: PersistedHistoryItem[]
  emptyMessage: string
  onTraceClick: (traceId: string) => void
}) {
  return (
    <div className={cn(INNER_TILE, 'mt-3')}>
      <p className={PERSISTED_HEADING}>Latest persisted agent logs</p>
      {props.logs.length === 0 ? (
        <p className={UI_TEXT.muted}>{props.emptyMessage}</p>
      ) : (
        <div className="space-y-1">
          {props.logs.slice(0, 10).map((log) => (
            <PersistedLogRow key={log.id} log={log} onTraceClick={props.onTraceClick} />
          ))}
        </div>
      )}
    </div>
  )
}

function PersistedLogRow(props: {
  log: PersistedHistoryItem
  onTraceClick: (traceId: string) => void
}) {
  const { log, onTraceClick } = props
  const handleClick = () => {
    if (log.trace_id) onTraceClick(log.trace_id)
  }
  return (
    <button type="button" onClick={handleClick} className={LIST_HOVER_BUTTON}>
      <span className={PERSISTED_SECONDARY_LABEL}>{log.kind}</span>
      <span className={PERSISTED_TERTIARY_LABEL}>{formatTimestamp(log.created_at)}</span>
    </button>
  )
}

function PersistedHistoryPanel(props: PersistedHistoryPanelProps) {
  const emptyMessage = emptyPersistedMessage(props.isInMemoryMode)
  return (
    <TerminalCard>
      <SectionHeader title="Persisted Event History" />
      <div className={SUB_PANEL_GRID_2}>
        <PersistedCountsCard counts={props.counts} emptyMessage={emptyMessage} />
        <PersistedEventsCard events={props.events} emptyMessage={emptyMessage} />
      </div>
      <PersistedLogsCard
        logs={props.logs}
        emptyMessage={emptyMessage}
        onTraceClick={props.onTraceClick}
      />
    </TerminalCard>
  )
}
