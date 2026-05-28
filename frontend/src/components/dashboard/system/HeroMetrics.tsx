'use client'

import { Brain, Database, Gauge, Wifi, WifiOff, Workflow, Zap } from 'lucide-react'

import { HeroMetric } from './HeroMetric'
import {
  PIPELINE_HEALTHY_LATENCY_MS,
  formatAgeFromMs,
  formatLlmProviderName,
  pipelineStatusTone,
} from './helpers'
import type { ApiHealth, PipelineStatus, WsDiagnosticsLike } from './types'

export interface HeroMetricsProps {
  pipelineStatus: PipelineStatus
  marketStageCount: number
  effectiveLatencyMs: number | null
  throughput: number
  wsConnected: boolean
  wsMessageCount: number
  wsDiagnostics: WsDiagnosticsLike
  isInMemoryMode: boolean
  apiHealth: ApiHealth
  llmAvailable: boolean | null
  llmProvider: string
}

const dbStatusLabel = (isInMemoryMode: boolean, state: ApiHealth['dashboardState']) => {
  if (isInMemoryMode) return 'Memory'
  if (state === 'ok') return 'Connected'
  if (state === 'error') return 'Error'
  return 'Pending'
}

const dbStatusTone = (
  isInMemoryMode: boolean,
  state: ApiHealth['dashboardState'],
): 'ok' | 'warn' | 'err' | 'neutral' => {
  if (isInMemoryMode) return 'warn'
  if (state === 'ok') return 'ok'
  if (state === 'error') return 'err'
  return 'neutral'
}

const llmStatusLabel = (available: boolean | null) => {
  if (available === false) return 'Rule-Based'
  if (available === true) return 'AI-Powered'
  return 'Unknown'
}

const llmStatusTone = (available: boolean | null): 'ok' | 'warn' | 'neutral' => {
  if (available === false) return 'warn'
  if (available === true) return 'ok'
  return 'neutral'
}

export function HeroMetrics(props: HeroMetricsProps) {
  const {
    pipelineStatus,
    marketStageCount,
    effectiveLatencyMs,
    throughput,
    wsConnected,
    wsMessageCount,
    wsDiagnostics,
    isInMemoryMode,
    apiHealth,
    llmAvailable,
    llmProvider,
  } = props

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <HeroMetric
        label="Pipeline"
        value={pipelineStatus}
        status={pipelineStatusTone(pipelineStatus)}
        icon={Workflow}
        sub={`${marketStageCount.toLocaleString()} market events`}
      />
      <HeroMetric
        label="Data Latency"
        value={effectiveLatencyMs != null ? formatAgeFromMs(effectiveLatencyMs) : '--'}
        status={
          effectiveLatencyMs == null
            ? 'neutral'
            : effectiveLatencyMs < PIPELINE_HEALTHY_LATENCY_MS
              ? 'ok'
              : 'warn'
        }
        icon={Gauge}
        sub={
          effectiveLatencyMs != null
            ? `${(effectiveLatencyMs / 1000).toFixed(1)}s since last event`
            : 'no recent activity'
        }
      />
      <HeroMetric
        label="Throughput"
        value={`${throughput.toFixed(2)}/s`}
        status={throughput > 0 ? 'ok' : 'neutral'}
        icon={Zap}
        sub={`${wsMessageCount.toLocaleString()} total msgs`}
      />
      <HeroMetric
        label="WebSocket"
        value={wsConnected ? 'Connected' : 'Disconnected'}
        status={wsConnected ? 'ok' : 'err'}
        icon={wsConnected ? Wifi : WifiOff}
        sub={`${wsDiagnostics.reconnectAttempts} reconnects`}
      />
      <HeroMetric
        label="Database"
        value={dbStatusLabel(isInMemoryMode, apiHealth.dashboardState)}
        status={dbStatusTone(isInMemoryMode, apiHealth.dashboardState)}
        icon={Database}
        sub={isInMemoryMode ? 'no persistence' : 'PostgreSQL'}
      />
      <HeroMetric
        label="LLM"
        value={llmStatusLabel(llmAvailable)}
        status={llmStatusTone(llmAvailable)}
        icon={Brain}
        sub={llmProvider ? formatLlmProviderName(llmProvider) : '—'}
      />
    </div>
  )
}
