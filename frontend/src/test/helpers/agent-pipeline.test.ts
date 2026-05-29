import { describe, it, expect } from 'vitest'

import {
  buildPipelineStages,
  PIPELINE_STAGE_DEFS,
  type AgentPipelineInput,
  type PipelineAgentLike,
  type PipelineStageKey,
  type PipelineStageView,
} from '@/lib/agent-pipeline'
import {
  AGENT_GRADE,
  AGENT_IC_UPDATER,
  AGENT_REASONING,
  AGENT_SIGNAL,
  AGENT_STRATEGY_PROPOSER,
  agentDisplayName,
} from '@/constants/agents'

function agent(
  name: string,
  status: PipelineAgentLike['status'],
  realtimeCount = 0,
  persistedCount = 0,
): PipelineAgentLike {
  return { name, status, realtimeCount, persistedCount, lastSeen: new Date() }
}

function stage(stages: PipelineStageView[], key: PipelineStageKey): PipelineStageView {
  const found = stages.find((s) => s.key === key)
  if (!found) throw new Error(`stage "${key}" not found`)
  return found
}

const EMPTY_INPUT: AgentPipelineInput = {
  agents: [],
  marketTickCount: 0,
  lastMarketSymbol: null,
  marketLive: false,
  decisionStats: null,
  proposalsCount: 0,
}

describe('buildPipelineStages', () => {
  it('returns one view per stage definition, in pipeline order (market + 7 agents)', () => {
    const stages = buildPipelineStages(EMPTY_INPUT)
    expect(stages.map((s) => s.key)).toEqual(PIPELINE_STAGE_DEFS.map((d) => d.key))
    expect(stages.map((s) => s.key)).toEqual([
      'market',
      'signal',
      'reasoning',
      'execution',
      'grade',
      'ic',
      'reflection',
      'proposer',
    ])
  })

  it('labels every agent stage via the shared agentDisplayName (uniform with the table)', () => {
    const stages = buildPipelineStages(EMPTY_INPUT)
    expect(stage(stages, 'signal').agent).toBe(agentDisplayName(AGENT_SIGNAL))
    expect(stage(stages, 'signal').agent).toBe('Signal Agent')
    expect(stage(stages, 'reasoning').agent).toBe('Reasoning Agent')
    expect(stage(stages, 'execution').agent).toBe('Execution Engine')
    expect(stage(stages, 'grade').agent).toBe('Grade Agent')
    expect(stage(stages, 'ic').agent).toBe(agentDisplayName(AGENT_IC_UPDATER))
    expect(stage(stages, 'proposer').agent).toBe('Strategy Proposer')
    // The market source has no agent — it shows its infra label.
    expect(stage(stages, 'market').agent).toBe('Price Poller')
  })

  it('defaults every stage to a zeroed, "none" state when nothing reports', () => {
    for (const s of buildPipelineStages(EMPTY_INPUT)) {
      expect(s.count).toBe(0)
      expect(Number.isNaN(s.count)).toBe(false)
      expect(s.tone).toBe('none')
    }
  })

  it('maps a reporting agent heartbeat to its stage count and tone', () => {
    const stages = buildPipelineStages({ ...EMPTY_INPUT, agents: [agent(AGENT_SIGNAL, 'Live', 12)] })
    expect(stage(stages, 'signal').count).toBe(12)
    expect(stage(stages, 'signal').tone).toBe('live')
  })

  it('sums realtime + persisted events for a stage count', () => {
    const stages = buildPipelineStages({ ...EMPTY_INPUT, agents: [agent(AGENT_GRADE, 'Live', 7, 5)] })
    expect(stage(stages, 'grade').count).toBe(12)
  })

  it('drives the market stage from marketTickCount + marketLive', () => {
    const live = buildPipelineStages({
      ...EMPTY_INPUT,
      marketTickCount: 60,
      marketLive: true,
      lastMarketSymbol: 'SPY',
    })
    expect(stage(live, 'market').count).toBe(60)
    expect(stage(live, 'market').tone).toBe('live')
    expect(stage(live, 'market').fact).toBe('last SPY')

    const idle = buildPipelineStages({ ...EMPTY_INPUT, marketTickCount: 5, marketLive: false })
    expect(stage(idle, 'market').tone).toBe('idle')
  })

  it('counts reasoning by heartbeat events and surfaces a buy/sell fact from decision stats', () => {
    const stages = buildPipelineStages({
      ...EMPTY_INPUT,
      agents: [agent(AGENT_REASONING, 'Live', 3)],
      decisionStats: { total: 8, last_hour: { buys: 4, sells: 3, holds: 1 } },
    })
    expect(stage(stages, 'reasoning').count).toBe(3)
    expect(stage(stages, 'reasoning').fact).toBe('4 buy · 3 sell')
  })

  it('does not throw on a partial decisionStats object (transient {} mid-fetch)', () => {
    expect(() => buildPipelineStages({ ...EMPTY_INPUT, decisionStats: {} })).not.toThrow()
    const stages = buildPipelineStages({ ...EMPTY_INPUT, decisionStats: {} })
    expect(stage(stages, 'reasoning').fact).toBeNull()
    expect(stage(stages, 'reasoning').count).toBe(0)
  })

  it('shows each learning agent as its own stage with the proposer surfacing proposal count', () => {
    const stages = buildPipelineStages({
      ...EMPTY_INPUT,
      agents: [agent(AGENT_IC_UPDATER, 'Idle', 2), agent(AGENT_STRATEGY_PROPOSER, 'Live', 1)],
      proposalsCount: 3,
    })
    expect(stage(stages, 'ic').count).toBe(2)
    expect(stage(stages, 'ic').tone).toBe('idle')
    expect(stage(stages, 'proposer').count).toBe(1)
    expect(stage(stages, 'proposer').tone).toBe('live')
    expect(stage(stages, 'proposer').fact).toBe('3 proposals')
  })

  it('singularizes the proposal fact for exactly one proposal', () => {
    const stages = buildPipelineStages({ ...EMPTY_INPUT, proposalsCount: 1 })
    expect(stage(stages, 'proposer').fact).toBe('1 proposal')
  })
})
