/**
 * Coerce a proposal's `content` into human-readable text.
 *
 * Most proposals carry `content` as a plain string. Challenger-promotion
 * proposals (and any future structured proposal) carry it as an OBJECT —
 * `{ strategy, shadow_edge, confidence, reason }` — which `String(obj)` turns
 * into the useless "[object Object]". Prefer the object's `reason`, then a
 * `strategy`-derived summary, before falling back to a JSON dump so nothing is
 * silently dropped on the floor.
 */
export function coerceProposalContent(raw: unknown): string {
  if (raw == null) return ''
  if (typeof raw === 'string') return raw
  if (typeof raw === 'object') {
    const obj = raw as Record<string, unknown>
    const reason = obj.reason
    if (typeof reason === 'string' && reason.trim()) return reason
    const strategy = obj.strategy
    if (typeof strategy === 'string' && strategy.trim()) return `Challenger: ${strategy}`
    try {
      return JSON.stringify(raw)
    } catch {
      return String(raw)
    }
  }
  return String(raw)
}

/** Pull a strategy name out of a structured (object) proposal content, if present. */
export function proposalStrategyName(raw: unknown): string | undefined {
  if (raw && typeof raw === 'object') {
    const strategy = (raw as Record<string, unknown>).strategy
    if (typeof strategy === 'string' && strategy.trim()) return strategy
  }
  return undefined
}
