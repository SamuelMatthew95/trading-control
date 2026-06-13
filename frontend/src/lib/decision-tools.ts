/**
 * Pure helpers for a decision's tool ledger — the reasoning chain the
 * ReasoningAgent now attaches to every decision (`tools_used`).
 *
 * The decision object is the container for its own reasoning: which tools it
 * exercised, how long they took, whether they succeeded, and a small summary of
 * what they returned. These helpers normalize the raw record and render that
 * summary; the panel only displays what they produce.
 */

export interface DecisionToolInvocation {
  name?: string
  latency_ms?: number
  success?: boolean
  outputs?: Record<string, unknown>
}

/** Read and normalize `tools_used` off a raw decision record. Total + safe. */
export function extractToolInvocations(decision: Record<string, unknown>): DecisionToolInvocation[] {
  const raw = decision.tools_used
  if (!Array.isArray(raw)) return []
  const out: DecisionToolInvocation[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const rec = item as Record<string, unknown>
    out.push({
      name: typeof rec.name === 'string' ? rec.name : undefined,
      latency_ms: typeof rec.latency_ms === 'number' ? rec.latency_ms : undefined,
      success: typeof rec.success === 'boolean' ? rec.success : undefined,
      outputs:
        rec.outputs && typeof rec.outputs === 'object'
          ? (rec.outputs as Record<string, unknown>)
          : undefined,
    })
  }
  return out
}

/**
 * Compact, human summary of a tool's decision-relevant output. Knows the
 * grounded shapes the backend emits today (similar-trade count, IC weights,
 * cross-stream confluence score + signal type) and degrades to `null` for
 * anything else so the row simply omits it.
 */
export function summarizeToolOutputs(outputs: Record<string, unknown> | undefined): string | null {
  if (!outputs || typeof outputs !== 'object') return null
  const parts: string[] = []

  if (typeof outputs.count === 'number') {
    parts.push(`${outputs.count} example${outputs.count === 1 ? '' : 's'}`)
  }

  // Order-book depth tool: spread (bps) and book imbalance — the live
  // microstructure the reasoning node saw at decision time.
  if (typeof outputs.spread_bps === 'number') {
    parts.push(`spread ${outputs.spread_bps.toFixed(1)}bps`)
  }
  if (typeof outputs.imbalance === 'number') {
    parts.push(`imbalance ${outputs.imbalance >= 0 ? '+' : ''}${outputs.imbalance.toFixed(3)}`)
  }

  // News-sentiment tool: signed sentiment over a count of recent articles.
  if (typeof outputs.sentiment === 'number') {
    const articles = typeof outputs.article_count === 'number' ? ` (${outputs.article_count})` : ''
    parts.push(`sentiment ${outputs.sentiment >= 0 ? '+' : ''}${outputs.sentiment.toFixed(2)}${articles}`)
  }

  // Macro-regime tool: the resolved regime label (and benchmark return if given).
  if (typeof outputs.regime === 'string' && outputs.regime) {
    const ret = typeof outputs.return_pct === 'number' ? ` ${outputs.return_pct >= 0 ? '+' : ''}${outputs.return_pct.toFixed(2)}%` : ''
    parts.push(`${outputs.regime}${ret}`)
  }

  // Cross-stream confluence tool: the composite score (and the signal type it
  // resolved to) the reasoning node folded from multiple market streams.
  if (typeof outputs.composite_score === 'number') {
    parts.push(`confluence ${outputs.composite_score.toFixed(2)}`)
  }
  if (typeof outputs.signal_type === 'string' && outputs.signal_type) {
    parts.push(outputs.signal_type)
  }

  const weights = outputs.ic_weights
  if (weights && typeof weights === 'object') {
    const entries = Object.entries(weights as Record<string, unknown>)
      .filter((entry): entry is [string, number] => typeof entry[1] === 'number')
      .slice(0, 3)
      .map(([key, value]) => `${key} ${value.toFixed(2)}`)
    parts.push(entries.length > 0 ? entries.join(' · ') : `${Object.keys(weights).length} factors`)
  }

  return parts.length > 0 ? parts.join(' · ') : null
}
