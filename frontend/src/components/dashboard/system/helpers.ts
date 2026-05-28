import type { PipelineStatus, StatusTone } from './types'

export const PRICE_FRESHNESS_MS = 60_000
export const PIPELINE_HEALTHY_LATENCY_MS = 15_000

export const SYSTEM_STREAMS = [
  'market_ticks',
  'market_events',
  'signals',
  'orders',
  'executions',
  'agent_logs',
  'risk_alerts',
  'notifications',
] as const

export const STATUS_COLOR: Record<StatusTone, string> = {
  ok: 'text-emerald-500',
  warn: 'text-amber-500',
  err: 'text-rose-500',
  neutral: 'text-slate-700 dark:text-slate-200',
}

export function formatTimestamp(value?: string | null): string {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleTimeString()
}

export function formatAgeFromMs(ageMs: number | null): string {
  if (ageMs == null || ageMs < 0 || !Number.isFinite(ageMs)) return '--'
  const sec = Math.floor(ageMs / 1000)
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m`
  const hr = Math.floor(min / 60)
  return `${hr}h`
}

export function resolveWsUrl(): string {
  if (typeof window === 'undefined') return '—'
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return (
      process.env.NEXT_PUBLIC_WS_URL.replace(/^https?:\/\//, 'wss://').replace(/\/$/, '') +
      '/ws/dashboard'
    )
  }
  if (process.env.NEXT_PUBLIC_API_URL) {
    return (
      process.env.NEXT_PUBLIC_API_URL.replace(/\/api\/?$/, '').replace(
        /^https?:\/\//,
        'wss://',
      ) + '/ws/dashboard'
    )
  }
  return window.location.host + '/ws/dashboard (same-origin)'
}

export function formatLlmProviderName(provider: string): string {
  if (!provider) return 'LLM'
  return provider.charAt(0).toUpperCase() + provider.slice(1)
}

export function canonicalAgentKey(name: string): string {
  return name.trim().toUpperCase().replace(/[\s-]+/g, '_')
}

export function pnlColorClass(value: number, isEmpty: boolean): string {
  if (isEmpty) return 'text-slate-500 dark:text-slate-400'
  if (value > 0) return 'text-emerald-500'
  if (value < 0) return 'text-rose-500'
  return 'text-slate-900 dark:text-slate-100'
}

export interface PipelineComputation {
  effectiveLatencyMs: number | null
  throughput: number
  pipelineStatus: PipelineStatus
  hasMarketData: boolean
  marketStageCount: number
  signalsCount: number
  ordersCount: number
  executionsCount: number
  marketTicksCount: number
  marketEventsCount: number
  pipelineWarning: boolean
  latestMarketTickTs: string | null
}

export interface PipelineInputs {
  streamStats: Record<string, { count: number; lastMessageTimestamp: string | null }>
  recentEvents: Array<{ stream?: string | null; timestamp?: string | null }>
  wsLastMessageTimestamp: string | null
  wsMessageRate: number
}

export function computePipeline({
  streamStats,
  recentEvents,
  wsLastMessageTimestamp,
  wsMessageRate,
}: PipelineInputs): PipelineComputation {
  const latestMarketTickTs = streamStats['market_ticks']?.lastMessageTimestamp ?? null
  const marketEventsTs = streamStats['market_events']?.lastMessageTimestamp ?? null
  const effectiveTickTs = latestMarketTickTs ?? marketEventsTs

  const dataLatencyMs = effectiveTickTs
    ? Math.max(Date.now() - new Date(effectiveTickTs).getTime(), 0)
    : null
  const wsLatencyMs = wsLastMessageTimestamp
    ? Math.max(Date.now() - new Date(wsLastMessageTimestamp).getTime(), 0)
    : null
  const recentEventLatencyMs =
    recentEvents.length > 0 && recentEvents[0]?.timestamp
      ? Math.max(Date.now() - new Date(recentEvents[0].timestamp).getTime(), 0)
      : null
  const effectiveLatencyMs = dataLatencyMs ?? wsLatencyMs ?? recentEventLatencyMs

  const marketTicksCount = streamStats['market_ticks']?.count ?? 0
  const marketEventsCount = streamStats['market_events']?.count ?? 0
  const signalsCount = streamStats['signals']?.count ?? 0
  const ordersCount = streamStats['orders']?.count ?? 0
  const executionsCount = streamStats['executions']?.count ?? 0
  const marketStageCount = marketEventsCount || marketTicksCount

  const hasMarketData = Boolean(
    latestMarketTickTs ||
      marketEventsTs ||
      marketTicksCount > 0 ||
      marketEventsCount > 0 ||
      recentEvents.some(
        (event) => event.stream === 'market_ticks' || event.stream === 'market_events',
      ),
  )

  const pipelineStatus: PipelineStatus = !hasMarketData
    ? 'Stalled'
    : effectiveLatencyMs != null && effectiveLatencyMs < PIPELINE_HEALTHY_LATENCY_MS
      ? 'Healthy'
      : 'Degraded'

  return {
    effectiveLatencyMs,
    throughput: Number.isFinite(wsMessageRate) ? Number(wsMessageRate) : 0,
    pipelineStatus,
    hasMarketData,
    marketStageCount,
    marketTicksCount,
    marketEventsCount,
    signalsCount,
    ordersCount,
    executionsCount,
    pipelineWarning: signalsCount > 0 && ordersCount === 0,
    latestMarketTickTs,
  }
}

export function pipelineStatusTone(status: PipelineStatus): StatusTone {
  if (status === 'Healthy') return 'ok'
  if (status === 'Degraded') return 'warn'
  return 'err'
}
