'use client'

import { AlertTriangle, ZapOff } from 'lucide-react'

import { AlertBanner } from '@/components/dashboard/system/AlertBanner'
import { LLMStatus, useLlmHealth } from '@/lib/llm-health'
import { UI_COPY } from '@/constants/copy'

/**
 * Page-level banner shown whenever the reasoning LLM is DEGRADED or DOWN.
 *
 * The LLM health panel buries status in a dot far down the page; an operator
 * needs to know at a glance when reasoning has dropped to fallback, because in
 * that state the agent fails closed — new signals are rejected rather than
 * traded on a naive momentum guess. Hidden while the model is live (or status
 * is "unknown" because no calls have happened yet) so it never nags during
 * normal operation.
 */
export function LLMDegradedBanner() {
  const { data } = useLlmHealth()
  if (!data) return null
  if (data.status !== LLMStatus.DEGRADED && data.status !== LLMStatus.DOWN) return null

  const down = data.status === LLMStatus.DOWN
  const successPct = Math.round(Number(data.success_rate_pct ?? 0))
  const fallbackNote = data.llm_fallback_enabled
    ? UI_COPY.llmDegraded.fallbackEnabled
    : UI_COPY.llmDegraded.fallbackDisabled
  // The downstream cascade is spelled out (UI_COPY.llmDegraded.cascade) so an
  // operator does not read the quiet pipeline as "everything is broken".

  return (
    <AlertBanner
      variant={down ? 'err' : 'warn'}
      icon={down ? ZapOff : AlertTriangle}
      message={`${down ? UI_COPY.llmDegraded.downMessage : UI_COPY.llmDegraded.degradedMessage} (${UI_COPY.llmDegraded.providerLabel} ${data.active_provider}).`}
      detail={`${UI_COPY.llmDegraded.successRateStem} ${successPct}% ${UI_COPY.llmDegraded.successRateWindow} ${fallbackNote}${UI_COPY.llmDegraded.cascade}`}
    />
  )
}
