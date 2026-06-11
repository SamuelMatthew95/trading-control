/**
 * Where does an approved proposal go? Mirrors the backend ProposalApplier
 * handler map (api/services/agents/proposal_applier.py): each proposal type is
 * routed deterministically to config (auto-PR), the in-process control plane /
 * registries, the prompt store, or a GitHub issue for human design.
 *
 * Surfacing this on the proposal queue makes the loop legible — the operator
 * sees at a glance whether approving will open a config PR or file an issue.
 */

export interface ProposalRouting {
  /** Short badge label. */
  label: string
  /** Whether the change is config/state-driven and applied by the system
   *  (auto-PR or control plane) vs. needing human code work (a GitHub issue)
   *  vs. an operator-only promotion that nothing auto-applies (`review`). */
  kind: 'config-pr' | 'control-plane' | 'prompt' | 'tool' | 'issue' | 'mixed' | 'review' | 'unknown'
  /** One-line explanation of the destination. */
  hint: string
}

const ROUTING: Record<string, ProposalRouting> = {
  parameter_change: {
    label: 'Config auto-PR',
    kind: 'config-pr',
    hint: 'Opens a pull request editing config/param_overrides.json (bounds-validated, no code edit).',
  },
  prompt_evolution: {
    label: 'Prompt store',
    kind: 'prompt',
    hint: 'Updates the versioned adaptive directive beneath the constitution.',
  },
  signal_weight_reduction: {
    label: 'Control plane',
    kind: 'control-plane',
    hint: 'Scales the global signal weight via Redis (reversible, TTL-bounded).',
  },
  agent_suspension: {
    label: 'Control plane',
    kind: 'control-plane',
    hint: 'Suspends the target agent for a bounded TTL via Redis.',
  },
  agent_retirement: {
    label: 'Control plane',
    kind: 'control-plane',
    hint: 'Pauses trading via the learning-loop circuit breaker.',
  },
  tool_governance: {
    label: 'Tool registry',
    kind: 'tool',
    hint: 'Disables the flagged tools so the next reasoning prompt drops them.',
  },
  new_agent: {
    label: 'Challenger / issue',
    kind: 'mixed',
    hint: 'Spawns a shadow challenger if its strategy is known, else files an issue.',
  },
  challenger_promotion: {
    label: 'Promote challenger',
    kind: 'review',
    hint: 'A shadow challenger beat its baseline on live data. Applies automatically by default (reasoning-directive bias + follow-up shadow spawn — no live orders); set CHALLENGER_PROMOTION_AUTO_APPLY=false to gate on operator approval.',
  },
  code_change: {
    label: 'GitHub issue',
    kind: 'issue',
    hint: 'Needs human design — filed as a GitHub issue, never auto-applied.',
  },
  regime_adjustment: {
    label: 'GitHub issue',
    kind: 'issue',
    hint: 'Needs human design — filed as a GitHub issue, never auto-applied.',
  },
}

const UNKNOWN: ProposalRouting = {
  label: 'Review',
  kind: 'unknown',
  hint: 'No automatic routing — operator review only.',
}

/** Resolve the routing for a proposal type (case-insensitive). Total. */
export function proposalRouting(proposalType: string | null | undefined): ProposalRouting {
  if (!proposalType) return UNKNOWN
  return ROUTING[proposalType.toLowerCase()] ?? UNKNOWN
}
