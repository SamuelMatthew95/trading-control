import { describe, it, expect } from 'vitest'

import { buildActivityTimeline } from '@/lib/activity-timeline'
import { STREAM_EXECUTIONS, STREAM_MARKET_TICKS, STREAM_SIGNALS } from '@/constants/streams'
import type { AgentLog, Notification, RecentEvent } from '@/stores/useCodexStore'

const iso = (msAgo: number) => new Date(Date.now() - msAgo).toISOString()

function notification(partial: Partial<Notification> & Pick<Notification, 'id'>): Notification {
  return {
    severity: 'INFO',
    message: 'msg',
    notification_type: 'system.test',
    timestamp: iso(0),
    ...partial,
  }
}

function agentLog(partial: Partial<AgentLog> & Pick<AgentLog, 'agent_name'>): AgentLog {
  return { timestamp: iso(0), ...partial }
}

describe('buildActivityTimeline', () => {
  it('turns a decision into a tone-coded, action-titled item', () => {
    const items = buildActivityTimeline({
      recentDecisions: [{ id: 'd1', action: 'buy', symbol: 'BTC/USD', confidence: 0.55, timestamp: iso(0) }],
    })
    expect(items).toHaveLength(1)
    expect(items[0].stage).toBe('decision')
    expect(items[0].title).toBe('BUY decided')
    expect(items[0].detail).toContain('BTC/USD')
    expect(items[0].detail).toContain('55%')
    expect(items[0].tone).toBe('buy')
  })

  it('flags rule-based fallback decisions', () => {
    const items = buildActivityTimeline({
      recentDecisions: [
        { id: 'a', action: 'buy', symbol: 'X', timestamp: iso(0), llm_succeeded: false },
        { id: 'b', action: 'sell', symbol: 'Y', timestamp: iso(1), reasoning_summary: 'fallback:skip_reasoning' },
        { id: 'c', action: 'hold', symbol: 'Z', timestamp: iso(2), llm_succeeded: true },
      ],
    })
    const byId = Object.fromEntries(items.map((i) => [i.detail?.split(' ')[0], i.fallback]))
    expect(byId['X']).toBe(true)
    expect(byId['Y']).toBe(true)
    expect(byId['Z']).toBe(false)
  })

  it('maps per-agent logs to stages with real detail, skipping reasoning/notification agents', () => {
    const items = buildActivityTimeline({
      agentLogs: [
        agentLog({ agent_name: 'SIGNAL_AGENT', action: 'buy', symbol: 'BTC/USD', timestamp: iso(10) }),
        agentLog({ agent_name: 'GRADE_AGENT', message: 'scored B', timestamp: iso(20) }),
        // Covered by the decisions / notifications sources — must not duplicate here.
        agentLog({ agent_name: 'REASONING_AGENT', action: 'buy', symbol: 'ETH/USD', timestamp: iso(30) }),
        agentLog({ agent_name: 'NOTIFICATION_AGENT', message: 'fired', timestamp: iso(40) }),
      ],
    })
    const byStage = Object.fromEntries(items.map((i) => [i.stage, i]))
    expect(items).toHaveLength(2)
    expect(byStage.signal.detail).toBe('buy BTC/USD')
    expect(byStage.signal.tone).toBe('buy')
    expect(byStage.grade.detail).toBe('scored B')
    expect(items.some((i) => i.stage === 'decision')).toBe(false)
  })

  it('skips agent lifecycle logs so spawn churn is not shown as pipeline output', () => {
    // An agent coming online writes an agent_log with log_type "lifecycle" and a
    // bare "lifecycle" message. These must NOT render as "Trade graded" /
    // "Reflection" / "Proposal drafted" — that contradicts the empty Proposals
    // and Learning pages when the loop is idle. A genuine output log (any other
    // log_type) for the same agent must still be surfaced.
    const items = buildActivityTimeline({
      agentLogs: [
        agentLog({ agent_name: 'GRADE_AGENT', message: 'lifecycle', log_type: 'lifecycle', timestamp: iso(10) }),
        agentLog({ agent_name: 'STRATEGY_PROPOSER', message: 'lifecycle', log_type: 'lifecycle', timestamp: iso(20) }),
        agentLog({ agent_name: 'REFLECTION_AGENT', message: 'lifecycle', log_type: 'lifecycle', timestamp: iso(30) }),
        agentLog({ agent_name: 'IC_UPDATER', message: 'lifecycle', log_type: 'lifecycle', timestamp: iso(40) }),
        // A real grade output still shows.
        agentLog({ agent_name: 'GRADE_AGENT', message: 'scored B', log_type: 'grade', timestamp: iso(50) }),
      ],
    })
    expect(items).toHaveLength(1)
    expect(items[0].stage).toBe('grade')
    expect(items[0].detail).toBe('scored B')
  })

  it('surfaces market stream events only — richer stages come from logs/decisions', () => {
    const recentEvents: RecentEvent[] = [
      { stream: STREAM_MARKET_TICKS, msgId: 'm1', timestamp: iso(10) },
      { stream: STREAM_SIGNALS, msgId: 's1', timestamp: iso(20) },
      { stream: STREAM_EXECUTIONS, msgId: 'e1', timestamp: iso(30) },
    ]
    const stages = buildActivityTimeline({ recentEvents }).map((i) => i.stage)
    expect(stages).toEqual(['market'])
  })

  it('shows the symbol + price + direction for a market event (no more bare rows)', () => {
    const recentEvents: RecentEvent[] = [
      { stream: STREAM_MARKET_TICKS, msgId: 'm1', timestamp: iso(10), symbol: 'BTC/USD', price: 60781.58, change: -12.3 },
    ]
    const [item] = buildActivityTimeline({ recentEvents })
    expect(item.detail).toBe('BTC/USD · $60,781.58 · ▼ 12.3')
  })

  it('leaves detail null when a market event carries no subject (no regression)', () => {
    const recentEvents: RecentEvent[] = [{ stream: STREAM_MARKET_TICKS, msgId: 'm1', timestamp: iso(10) }]
    expect(buildActivityTimeline({ recentEvents })[0].detail).toBeNull()
  })

  it('merges all sources newest-first', () => {
    const items = buildActivityTimeline({
      recentDecisions: [{ id: 'd', action: 'buy', symbol: 'BTC/USD', timestamp: iso(5_000) }],
      notifications: [notification({ id: 'n', title: 'BUY filled', timestamp: iso(1_000) })],
      agentLogs: [agentLog({ agent_name: 'SIGNAL_AGENT', symbol: 'BTC/USD', timestamp: iso(9_000) })],
      recentEvents: [{ stream: STREAM_MARKET_TICKS, msgId: 'm', timestamp: iso(12_000) }],
    })
    expect(items.map((i) => i.stage)).toEqual(['notification', 'decision', 'signal', 'market'])
  })

  it('skips items with unparseable timestamps and caps the result', () => {
    const decisions = Array.from({ length: 60 }, (_, i) => ({
      id: `d${i}`,
      action: 'buy',
      symbol: 'X',
      timestamp: iso(i),
    }))
    decisions.push({ id: 'bad', action: 'buy', symbol: 'X', timestamp: 'not-a-date' })
    const items = buildActivityTimeline({ recentDecisions: decisions }, 40)
    expect(items).toHaveLength(40)
    expect(items.some((i) => i.id === 'decision-bad')).toBe(false)
  })

  it('returns an empty array for empty input', () => {
    expect(buildActivityTimeline({})).toEqual([])
  })
})
