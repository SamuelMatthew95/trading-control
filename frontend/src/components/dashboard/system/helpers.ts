import type { PipelineStatus } from './types'

/** Latency above which the data pipeline reads as Degraded rather than Healthy. */
export const PIPELINE_HEALTHY_LATENCY_MS = 15_000

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
