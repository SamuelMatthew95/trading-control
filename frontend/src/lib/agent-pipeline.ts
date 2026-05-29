/**
 * Pure logic for the Agents dashboard pipeline view.
 *
 * This module is deliberately free of React and styling so the mapping from
 * raw store/REST data → ordered pipeline stages can be unit-tested in
 * isolation. The component (`AgentPipeline.tsx`) only renders what this
 * produces.
 *
 * The pipeline mirrors the documented 7-agent system:
 *   Market → Signal → Reasoning → Execution → Grade → {IC, Reflection, Proposer}
 * Grades and re-weighted factors loop back into Reasoning (the learning loop).
 */
import {
  AGENT_EXECUTION,
  AGENT_GRADE,
  AGENT_IC_UPDATER,
  AGENT_REASONING,
  AGENT_REFLECTION,
  AGENT_SIGNAL,
  AGENT_STRATEGY_PROPOSER,
  canonicalAgentKey,
} from '@/constants/agents'

/** Status vocabulary shared with DashboardView's `AgentSummary`. */
export type PipelineAgentStatus = 'Live' | 'Stale' | 'Error' | 'Idle'

/** Structural subset of `AgentSummary` this module needs. */
export interface PipelineAgentLike {
  name: string
  status: PipelineAgentStatus
  realtimeCount: number
  persistedCount: number
  lastSeen: Date | null
}

export type StageTone = 'live' | 'stale' | 'error' | 'idle' | 'none'

export type PipelineStageKey = 'market' | 'signal' | 'reasoning' | 'execution' | 'grade' | 'learn'

export interface PipelineStageDef {
  key: PipelineStageKey
  label: string
  /** Human-readable agent name(s) for this stage. */
  agent: string
  /** One line describing what the stage does — grounded in the agent's role. */
  does: string
  /** Unit for the throughput count ("signals", "decisions", …). */
  unit: string
  /** Canonical agent-name constants this stage aggregates (empty for infra stages). */
  agentKeys: readonly string[]
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
  agent: string
  does: string
  unit: string
  count: number
  fact: string | null
  tone: StageTone
}

/**
 * Static description of every pipeline stage. The dynamic count/status/fact
 * are layered on by `buildPipelineStages` — this array is just the contract
 * of "what each agent is and does".
 */
export const PIPELINE_STAGE_DEFS: readonly PipelineStageDef[] = [
  {
    key: 'market',
    label: 'Market',
    agent: 'Price Poller',
    does: 'Streams live market prices',
    unit: 'ticks',
    agentKeys: [],
  },
  {
    key: 'signal',
    label: 'Signal',
    agent: 'SignalGenerator',
    does: 'Turns market ticks into trade signals',
    unit: 'signals',
    agentKeys: [AGENT_SIGNAL],
  },
  {
    key: 'reasoning',
    label: 'Reasoning',
    agent: 'ReasoningAgent',
    does: 'LLM weighs signals into buy / sell / hold',
    unit: 'decisions',
    agentKeys: [AGENT_REASONING],
  },
  {
    key: 'execution',
    label: 'Execution',
    agent: 'ExecutionEngine',
    does: 'Places orders and records fills',
    unit: 'orders',
    agentKeys: [AGENT_EXECUTION],
  },
  {
    key: 'grade',
    label: 'Grade',
    agent: 'GradeAgent',
    does: 'Scores how each trade performed',
    unit: 'graded',
    agentKeys: [AGENT_GRADE],
  },
  {
    key: 'learn',
    label: 'Learn',
    agent: 'IC · Reflection · Proposer',
    does: 'Re-weights factors and proposes new strategies',
    unit: 'updates',
    agentKeys: [AGENT_IC_UPDATER, AGENT_REFLECTION, AGENT_STRATEGY_PROPOSER],
  },
]

const STATUS_TO_TONE: Record<PipelineAgentStatus, StageTone> = {
  Live: 'live',
  Stale: 'stale',
  Error: 'error',
  Idle: 'idle',
}

/** Lower number = "more alive"; used to fold multiple agents into one stage tone. */
const TONE_PRIORITY: Record<StageTone, number> = { live: 0, stale: 1, error: 2, idle: 3, none: 4 }

function indexAgents(agents: PipelineAgentLike[]): Map<string, PipelineAgentLike> {
  const byKey = new Map<string, PipelineAgentLike>()
  for (const agent of agents) byKey.set(canonicalAgentKey(agent.name), agent)
  return byKey
}

function eventsOf(agent: PipelineAgentLike | undefined): number {
  if (!agent) return 0
  return (agent.realtimeCount ?? 0) + (agent.persistedCount ?? 0)
}

function toneOf(agent: PipelineAgentLike | undefined): StageTone {
  return agent ? STATUS_TO_TONE[agent.status] ?? 'none' : 'none'
}

function combineTone(tones: StageTone[]): StageTone {
  return tones.reduce<StageTone>((best, tone) => (TONE_PRIORITY[tone] < TONE_PRIORITY[best] ? tone : best), 'none')
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
    case 'learn':
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
    const stageAgents = def.agentKeys.map((agentKey) => byKey.get(agentKey))
    const agentEvents = stageAgents.reduce((sum, agent) => sum + eventsOf(agent), 0)

    let count: number
    if (def.key === 'market') {
      count = input.marketTickCount
    } else if (def.key === 'reasoning') {
      // Prefer the authoritative decision count; fall back to heartbeat events.
      count = input.decisionStats?.total ?? agentEvents
    } else {
      count = agentEvents
    }

    const tone = def.key === 'market' ? marketTone(input) : combineTone(stageAgents.map(toneOf))

    return {
      key: def.key,
      label: def.label,
      agent: def.agent,
      does: def.does,
      unit: def.unit,
      count,
      fact: factFor(def.key, input),
      tone,
    }
  })
}
