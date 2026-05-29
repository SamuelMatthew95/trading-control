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
  it('returns one view per stage definition, in pipeline order', () => {
    const stages = buildPipelineStages(EMPTY_INPUT)
    expect(stages.map((s) => s.key)).toEqual(PIPELINE_STAGE_DEFS.map((d) => d.key))
    expect(stages.map((s) => s.key)).toEqual([
      'market',
      'signal',
      'reasoning',
      'execution',
      'grade',
      'learn',
    ])
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

  it('sums realtime + persisted events for a stage', () => {
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

  it('prefers decisionStats.total for the reasoning count and shows a buy/sell fact', () => {
    const stages = buildPipelineStages({
      ...EMPTY_INPUT,
      agents: [agent(AGENT_REASONING, 'Live', 3)],
      decisionStats: { total: 8, last_hour: { buys: 4, sells: 3, holds: 1 } },
    })
    expect(stage(stages, 'reasoning').count).toBe(8)
    expect(stage(stages, 'reasoning').fact).toBe('4 buy · 3 sell')
  })

  it('falls back to reasoning heartbeat events when decisionStats is absent', () => {
    const stages = buildPipelineStages({ ...EMPTY_INPUT, agents: [agent(AGENT_REASONING, 'Stale', 5)] })
    expect(stage(stages, 'reasoning').count).toBe(5)
  })

  it('does not throw on a partial decisionStats object (transient {} mid-fetch)', () => {
    expect(() => buildPipelineStages({ ...EMPTY_INPUT, decisionStats: {} })).not.toThrow()
    const stages = buildPipelineStages({ ...EMPTY_INPUT, decisionStats: {} })
    expect(stage(stages, 'reasoning').fact).toBeNull()
    expect(stage(stages, 'reasoning').count).toBe(0)
  })

  it('aggregates the three learning agents into the learn stage and surfaces proposals', () => {
    const stages = buildPipelineStages({
      ...EMPTY_INPUT,
      agents: [agent(AGENT_IC_UPDATER, 'Idle', 2), agent(AGENT_STRATEGY_PROPOSER, 'Live', 1, 1)],
      proposalsCount: 3,
    })
    expect(stage(stages, 'learn').count).toBe(4)
    expect(stage(stages, 'learn').tone).toBe('live')
    expect(stage(stages, 'learn').fact).toBe('3 proposals')
  })

  it('singularizes the proposal fact for exactly one proposal', () => {
    const stages = buildPipelineStages({ ...EMPTY_INPUT, proposalsCount: 1 })
    expect(stage(stages, 'learn').fact).toBe('1 proposal')
  })
})
