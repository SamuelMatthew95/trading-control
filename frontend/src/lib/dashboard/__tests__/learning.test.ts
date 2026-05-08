import { describe, it, expect } from 'vitest'
import {
  buildCleanGradeHistory,
  buildLearningSummary,
  buildPipelineStages,
} from '../learning'

import type { GradeRecord } from '@/lib/api'
import type { Order, Proposal, TradeFeedItem } from '@/stores/useCodexStore'

const FIXED_NOW = new Date('2026-05-08T12:00:00Z').getTime()

function isoMinusMinutes(min: number): string {
  return new Date(FIXED_NOW - min * 60_000).toISOString()
}

const noStreamStats = {} as Record<string, { count: number; lastMessageTimestamp: string | null }>

describe('buildCleanGradeHistory', () => {
  it('removes entries with no grade and no score', () => {
    const grades: GradeRecord[] = [
      { grade: '', score_pct: NaN as unknown as number, timestamp: isoMinusMinutes(1) },
      { grade: 'A', score_pct: 80, timestamp: isoMinusMinutes(2) },
    ]
    const result = buildCleanGradeHistory(grades)
    expect(result).toHaveLength(1)
    expect(result[0].grade).toBe('A')
  })

  it('removes entries with unparseable timestamp', () => {
    const grades: GradeRecord[] = [
      { grade: 'A', score_pct: 80, timestamp: 'garbage' },
    ]
    expect(buildCleanGradeHistory(grades)).toEqual([])
  })

  it('sorts newest first', () => {
    const grades: GradeRecord[] = [
      { grade: 'A', score_pct: 80, timestamp: isoMinusMinutes(10) },
      { grade: 'B', score_pct: 70, timestamp: isoMinusMinutes(2) },
    ]
    const result = buildCleanGradeHistory(grades)
    expect(result[0].grade).toBe('B')
    expect(result[1].grade).toBe('A')
  })

  it('deduplicates exact duplicates', () => {
    const ts = isoMinusMinutes(1)
    const grades: GradeRecord[] = [
      { grade: 'A', score_pct: 80, timestamp: ts },
      { grade: 'A', score_pct: 80, timestamp: ts },
    ]
    expect(buildCleanGradeHistory(grades)).toHaveLength(1)
  })
})

describe('buildLearningSummary', () => {
  it('uses max of stream count vs event count vs grade history length', () => {
    const grades: GradeRecord[] = [
      { grade: 'A', score_pct: 80, timestamp: isoMinusMinutes(1) },
      { grade: 'B', score_pct: 70, timestamp: isoMinusMinutes(2) },
    ]
    const summary = buildLearningSummary(
      { agent_grades: { count: 1, lastMessageTimestamp: null } },
      [{ type: 'trade_evaluated' }],
      grades,
      {},
      [],
      [],
    )
    expect(summary.tradesEvaluated).toBe(2)
  })

  it('counts strategiesTested as max(events, proposals)', () => {
    const proposals = [{}, {}, {}] as unknown as Proposal[]
    const summary = buildLearningSummary(noStreamStats, [], [], {}, proposals, [])
    expect(summary.strategiesTested).toBe(3)
  })

  it('best/worst day surfaces from per-day pnl bucket', () => {
    const orders = [
      { pnl: 30, timestamp: '2026-05-07T10:00:00Z' },
      { pnl: -50, timestamp: '2026-05-08T10:00:00Z' },
      { pnl: 100, timestamp: '2026-05-09T10:00:00Z' },
    ] as unknown as Order[]
    const summary = buildLearningSummary(noStreamStats, [], [], {}, [], orders)
    expect(summary.bestDay?.[1]).toBe(100)
    expect(summary.worstDay?.[1]).toBe(-50)
  })

  it('icValuesUpdated reflects ic weights presence', () => {
    const summary = buildLearningSummary(noStreamStats, [], [], { factor: 0.5 }, [], [])
    expect(summary.icValuesUpdated).toBeGreaterThanOrEqual(1)
  })
})

describe('buildPipelineStages', () => {
  it('returns five stages in order', () => {
    const stages = buildPipelineStages([], [], 0, 0, [], noStreamStats, FIXED_NOW)
    expect(stages.map((s) => s.key)).toEqual([
      'ingestion',
      'grading',
      'reflection',
      'proposals',
      'ic',
    ])
  })

  it('marks grading Error when trades exist but no grades', () => {
    const trades = [{}] as TradeFeedItem[]
    const stages = buildPipelineStages(trades, [], 0, 0, [], noStreamStats, FIXED_NOW)
    const grading = stages.find((s) => s.key === 'grading')!
    expect(grading.status).toBe('Error')
  })

  it('marks ingestion Idle on empty input', () => {
    const stages = buildPipelineStages([], [], 0, 0, [], noStreamStats, FIXED_NOW)
    const ingestion = stages.find((s) => s.key === 'ingestion')!
    expect(ingestion.status).toBe('Idle')
  })

  it('marks ingestion Active when trades + recent timestamp', () => {
    const trades = [
      { filled_at: isoMinusMinutes(1), created_at: null } as unknown as TradeFeedItem,
    ]
    const stages = buildPipelineStages(trades, [], 0, 0, [], noStreamStats, FIXED_NOW)
    const ingestion = stages.find((s) => s.key === 'ingestion')!
    expect(ingestion.status).toBe('Active')
  })
})
