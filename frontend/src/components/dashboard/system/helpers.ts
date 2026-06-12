import {
  STREAM_EXECUTIONS,
  STREAM_MARKET_EVENTS,
  STREAM_MARKET_TICKS,
  STREAM_ORDERS,
  STREAM_SIGNALS,
} from '@/constants/streams'
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
  const latestMarketTickTs = streamStats[STREAM_MARKET_TICKS]?.lastMessageTimestamp ?? null
  const marketEventsTs = streamStats[STREAM_MARKET_EVENTS]?.lastMessageTimestamp ?? null
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

  const marketTicksCount = streamStats[STREAM_MARKET_TICKS]?.count ?? 0
  const marketEventsCount = streamStats[STREAM_MARKET_EVENTS]?.count ?? 0
  const signalsCount = streamStats[STREAM_SIGNALS]?.count ?? 0
  const ordersCount = streamStats[STREAM_ORDERS]?.count ?? 0
  const executionsCount = streamStats[STREAM_EXECUTIONS]?.count ?? 0
  const marketStageCount = marketEventsCount || marketTicksCount

  const hasMarketData = Boolean(
    latestMarketTickTs ||
      marketEventsTs ||
      marketTicksCount > 0 ||
      marketEventsCount > 0 ||
      recentEvents.some(
        (event) => event.stream === STREAM_MARKET_TICKS || event.stream === STREAM_MARKET_EVENTS,
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
