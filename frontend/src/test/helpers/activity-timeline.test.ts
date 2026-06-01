import { describe, it, expect } from 'vitest'

import { buildActivityTimeline } from '@/lib/activity-timeline'
import {
  STREAM_AGENT_GRADES,
  STREAM_DECISIONS,
  STREAM_EXECUTIONS,
  STREAM_NOTIFICATIONS,
  STREAM_SIGNALS,
} from '@/constants/streams'
import type { Notification, RecentEvent } from '@/stores/useCodexStore'

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

  it('includes raw stage events but not the streams that have a richer source', () => {
    const recentEvents: RecentEvent[] = [
      { stream: STREAM_SIGNALS, msgId: 's1', timestamp: iso(10) },
      { stream: STREAM_EXECUTIONS, msgId: 'e1', timestamp: iso(20) },
      { stream: STREAM_AGENT_GRADES, msgId: 'g1', timestamp: iso(30) },
      // These map to richer dedicated sources and must be skipped as raw events.
      { stream: STREAM_DECISIONS, msgId: 'x1', timestamp: iso(40) },
      { stream: STREAM_NOTIFICATIONS, msgId: 'n1', timestamp: iso(50) },
    ]
    const stages = buildActivityTimeline({ recentEvents }).map((i) => i.stage)
    expect(stages).toContain('signal')
    expect(stages).toContain('execution')
    expect(stages).toContain('grade')
    // Only the three non-richer streams survive.
    expect(stages).toHaveLength(3)
  })

  it('merges all sources newest-first', () => {
    const items = buildActivityTimeline({
      recentDecisions: [{ id: 'd', action: 'buy', symbol: 'BTC/USD', timestamp: iso(5_000) }],
      notifications: [notification({ id: 'n', title: 'BUY filled', timestamp: iso(1_000) })],
      recentEvents: [{ stream: STREAM_SIGNALS, msgId: 's', timestamp: iso(9_000) }],
    })
    expect(items.map((i) => i.stage)).toEqual(['notification', 'decision', 'signal'])
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
