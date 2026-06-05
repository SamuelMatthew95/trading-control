'use client'

import { AlertTriangle, ZapOff } from 'lucide-react'

import { AlertBanner } from '@/components/dashboard/system/AlertBanner'
import { LLMStatus, useLlmHealth } from '@/lib/llm-health'

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
    ? 'Cloud fallback is enabled.'
    : 'Cloud fallback is disabled — reasoning fails closed (new signals are rejected, no naive trades).'
  // Spell out the downstream cascade so an operator does not read the quiet
  // pipeline as "everything is broken": while reasoning is degraded few/no
  // trades close, so the learning agents stay idle — the wiring is intact, the
  // pipeline is just waiting for the LLM to recover.
  const cascade =
    ' Knock-on: with reasoning degraded, few/no trades close, so the learning agents' +
    ' (Grade · IC · Reflection · Proposer) sit idle until trading resumes — wiring is intact,' +
    ' the pipeline is waiting on the LLM.'

  return (
    <AlertBanner
      variant={down ? 'err' : 'warn'}
      icon={down ? ZapOff : AlertTriangle}
      message={
        down
          ? `Reasoning LLM down — running in fallback mode (provider: ${data.active_provider}).`
          : `Reasoning LLM degraded — decision quality reduced (provider: ${data.active_provider}).`
      }
      detail={`LLM success rate ${successPct}% over the last window. ${fallbackNote}${cascade}`}
    />
  )
}
