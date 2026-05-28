'use client'

import { AlertTriangle, Brain, Database, Radio, ServerCrash } from 'lucide-react'

import { AlertBanner } from './AlertBanner'
import { formatLlmProviderName } from './helpers'

export interface SystemAlertsProps {
  pipelineWarning: boolean
  hasMarketData: boolean
  latestMarketTickTs: string | null
  systemFeedError: string | null
  persistenceEnabled: boolean
  llmAvailable: boolean | null
  llmProvider: string
}

export function SystemAlerts(props: SystemAlertsProps) {
  const {
    pipelineWarning,
    hasMarketData,
    latestMarketTickTs,
    systemFeedError,
    persistenceEnabled,
    llmAvailable,
    llmProvider,
  } = props

  const showAlerts =
    pipelineWarning ||
    !hasMarketData ||
    (hasMarketData && !latestMarketTickTs) ||
    Boolean(systemFeedError) ||
    !persistenceEnabled ||
    llmAvailable === false

  if (!showAlerts) return null

  return (
    <div className="space-y-2">
      {pipelineWarning && (
        <AlertBanner
          variant="warn"
          icon={AlertTriangle}
          message="Signals generated but no orders placed"
          detail="Reasoning is producing decisions that aren't reaching execution. Check the reasoning → execution handoff."
        />
      )}
      {!hasMarketData && (
        <AlertBanner
          variant="err"
          icon={ServerCrash}
          message="No market data received"
          detail="WebSocket isn't streaming market_ticks or market_events. Check Alpaca / price poller connection."
        />
      )}
      {hasMarketData && !latestMarketTickTs && (
        <AlertBanner
          variant="warn"
          icon={Radio}
          message="Market events arriving, market_ticks missing"
          detail="Live prices flow via WebSocket, but per-tick data isn't being recorded — lag metrics will be incomplete."
        />
      )}
      {systemFeedError && (
        <AlertBanner variant="err" icon={AlertTriangle} message={systemFeedError} />
      )}
      {!persistenceEnabled && (
        <AlertBanner
          variant="warn"
          icon={Database}
          message="Persistence disabled"
          detail="No persisted events/logs detected. Agent history and learning data won't survive restarts."
        />
      )}
      {llmAvailable === false && (
        <AlertBanner
          variant="info"
          icon={Brain}
          message="Rule-based reasoning mode"
          detail={`No ${formatLlmProviderName(llmProvider)} API key configured. Decisions use signal direction only — set ${
            llmProvider ? llmProvider.toUpperCase() + '_API_KEY' : 'an LLM API key'
          } to enable AI-powered analysis.`}
        />
      )}
    </div>
  )
}
