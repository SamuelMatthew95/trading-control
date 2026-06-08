/**
 * Pure logic for the Agents dashboard pipeline view.
 *
 * No React or styling here so the mapping from raw store/REST data → ordered
 * pipeline stages can be unit-tested in isolation. The component
 * (`AgentPipeline.tsx`) only renders what this produces.
 *
 * Mirrors the documented 7-agent system:
 *   Market → Signal → Reasoning → Execution → Grade → IC Update → Reflection → Proposer
 * Grades and re-weighted factors loop back into Reasoning (the learning loop).
 * Every stage's displayed agent name comes from `agentDisplayName`, so the
 * pipeline and the Agent Status table always show the same label for an agent.
 */
import {
  AGENT_EXECUTION,
  AGENT_GRADE,
  AGENT_IC_UPDATER,
  AGENT_REASONING,
  AGENT_REFLECTION,
  AGENT_SIGNAL,
  AGENT_STRATEGY_PROPOSER,
  agentDisplayName,
  canonicalAgentKey,
} from '@/constants/agents'
import type { AgentStatus } from '@/types/dashboard'

/** Canonical agent display status — `AgentStatus` is the single definition. */
export type PipelineAgentStatus = AgentStatus

/** Structural subset of `AgentSummary` this module needs. */
export interface PipelineAgentLike {
  name: string
  status: PipelineAgentStatus
  /**
   * The agent's processed-event tally — ONE canonical number, never a sum of
   * sources. Sourced with strict precedence (heartbeat > logs > lifecycle) so
   * the pipeline, the Agent Status table, and the Scorecards all show the same
   * count for an agent. See `buildAgentSummaries` in `DashboardView`.
   */
  eventCount: number
  lastSeen: Date | null
}

/**
 * The dashboard's reconciled per-agent rollup (heartbeats + logs + lifecycle
 * rows). Shared by the Agents view and its pipeline so both agree on shape.
 */
export interface AgentSummary extends PipelineAgentLike {
  tier: 'active' | 'challenger' | 'inactive'
  source: 'realtime' | 'persisted' | 'hybrid'
}

export type StageTone = 'live' | 'stale' | 'error' | 'idle' | 'none'

export type PipelineStageKey =
  | 'market'
  | 'signal'
  | 'reasoning'
  | 'execution'
  | 'grade'
  | 'ic'
  | 'reflection'
  | 'proposer'

export interface PipelineStageDef {
  key: PipelineStageKey
  /** Short flow-step tag shown on the node. */
  label: string
  /** One line describing what the stage does — grounded in the agent's role. */
  does: string
  /** Unit for the throughput count ("signals", "decisions", …). */
  unit: string
  /** Canonical agent-name constant this stage maps to (null for the infra source). */
  agentKey: string | null
  /** Display name for stages with no agent (the market data source). */
  infraLabel?: string
}

/** Minimal shape of `/decisions/stats` — fields optional so a partial `{}` mid-fetch is safe. */
export interface DecisionStatsLike {
  total?: number | null
  last_hour?: { buys: number; sells: number; holds: number } | null
}

export interface AgentPipelineInput {
  agents: PipelineAgentLike[]
  marketTickCount: number
  lastMarketSymbol: string | null
  marketLive: boolean
  decisionStats: DecisionStatsLike | null
  proposalsCount: number
}

export interface PipelineStageView {
  key: PipelineStageKey
  label: string
  /** The agent's display name — identical to the Agent Status table's label. */
  agent: string
  does: string
  unit: string
  count: number
  fact: string | null
  tone: StageTone
}

/**
 * Static description of every pipeline stage: the contract of "what each agent
 * is and does". Dynamic count/status/fact are layered on by `buildPipelineStages`.
 */
export const PIPELINE_STAGE_DEFS: readonly PipelineStageDef[] = [
  { key: 'market', label: 'Market', does: 'Streams live market prices', unit: 'ticks', agentKey: null, infraLabel: 'Price Poller' },
  { key: 'signal', label: 'Signal', does: 'Turns market ticks into trade signals', unit: 'signals', agentKey: AGENT_SIGNAL },
  { key: 'reasoning', label: 'Reasoning', does: 'LLM weighs signals into buy / sell / hold', unit: 'decisions', agentKey: AGENT_REASONING },
  { key: 'execution', label: 'Execution', does: 'Places orders and records fills', unit: 'orders', agentKey: AGENT_EXECUTION },
  { key: 'grade', label: 'Grade', does: 'Scores how each trade performed', unit: 'grades', agentKey: AGENT_GRADE },
  { key: 'ic', label: 'IC Update', does: 'Re-weights signal factors from results', unit: 'updates', agentKey: AGENT_IC_UPDATER },
  { key: 'reflection', label: 'Reflection', does: 'Forms improvement hypotheses', unit: 'reflections', agentKey: AGENT_REFLECTION },
  { key: 'proposer', label: 'Proposer', does: 'Proposes new strategies', unit: 'proposals', agentKey: AGENT_STRATEGY_PROPOSER },
]

const STATUS_TO_TONE: Record<PipelineAgentStatus, StageTone> = {
  Live: 'live',
  Stale: 'stale',
  Error: 'error',
  Idle: 'idle',
}

function indexAgents(agents: PipelineAgentLike[]): Map<string, PipelineAgentLike> {
  const byKey = new Map<string, PipelineAgentLike>()
  for (const agent of agents) byKey.set(canonicalAgentKey(agent.name), agent)
  return byKey
}

function eventsOf(agent: PipelineAgentLike | undefined): number {
  if (!agent) return 0
  return agent.eventCount ?? 0
}

function toneOf(agent: PipelineAgentLike | undefined): StageTone {
  return agent ? STATUS_TO_TONE[agent.status] ?? 'none' : 'none'
}

function marketTone(input: AgentPipelineInput): StageTone {
  if (input.marketLive) return 'live'
  return input.marketTickCount > 0 ? 'idle' : 'none'
}

function factFor(key: PipelineStageKey, input: AgentPipelineInput): string | null {
  switch (key) {
    case 'market':
      return input.lastMarketSymbol ? `last ${input.lastMarketSymbol}` : null
    case 'reasoning': {
      const hour = input.decisionStats?.last_hour
      return hour ? `${hour.buys} buy · ${hour.sells} sell` : null
    }
    case 'proposer':
      return input.proposalsCount > 0
        ? `${input.proposalsCount} proposal${input.proposalsCount === 1 ? '' : 's'}`
        : null
    default:
      return null
  }
}

/** Map raw store/REST data onto the ordered pipeline stages. Pure + total. */
export function buildPipelineStages(input: AgentPipelineInput): PipelineStageView[] {
  const byKey = indexAgents(input.agents)

  return PIPELINE_STAGE_DEFS.map((def) => {
    const agent = def.agentKey ? byKey.get(def.agentKey) : undefined
    const isMarket = def.key === 'market'
    return {
      key: def.key,
      label: def.label,
      // One source of truth for the label, shared with the Agent Status table.
      agent: def.agentKey ? agentDisplayName(def.agentKey) : def.infraLabel ?? def.label,
      does: def.does,
      unit: def.unit,
      count: isMarket ? input.marketTickCount : eventsOf(agent),
      fact: factFor(def.key, input),
      tone: isMarket ? marketTone(input) : toneOf(agent),
    }
  })
}
