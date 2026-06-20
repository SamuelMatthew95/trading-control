/**
 * Coerce a proposal's `content` into human-readable text.
 *
 * Most proposals carry `content` as a plain string. Challenger-promotion
 * proposals (and any future structured proposal) carry it as an OBJECT —
 * `{ strategy, shadow_edge, confidence, reason }` — which `String(obj)` turns
 * into the useless "[object Object]". Prefer the object's `reason`/`description`,
 * then a `strategy`-derived summary; an EMPTY object (the memory-mode
 * `content: {}` shape) becomes '' so the UI can fall back to
 * strategy_name / proposal_type; otherwise fall back to a JSON dump so nothing
 * is silently dropped on the floor.
 */
export function coerceProposalContent(raw: unknown): string {
  if (raw == null) return ''
  if (typeof raw === 'string') return raw
  if (typeof raw === 'object') {
    const obj = raw as Record<string, unknown>
    // Prefer a human-readable summary field over a JSON dump. `reason` rides on
    // challenger/grade proposals; `description` on design/issue proposals — which
    // ALSO carry a large `brief` markdown that must never be rendered as a blob.
    for (const key of ['reason', 'description'] as const) {
      const value = obj[key]
      if (typeof value === 'string' && value.trim()) return value
    }
    const strategy = obj.strategy
    if (typeof strategy === 'string' && strategy.trim()) return `Challenger: ${strategy}`
    // An empty object (the memory-mode `content: {}` shape) renders as '' so the
    // UI falls back to strategy_name / proposal_type instead of a bare "{}".
    if (Object.keys(obj).length === 0) return ''
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
