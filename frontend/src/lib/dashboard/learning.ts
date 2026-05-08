/**
 * Learning-domain selectors.
 */

import type { GradeRecord } from '@/lib/api'
import type { Order, Proposal, TradeFeedItem } from '@/stores/useCodexStore'
import { parseTimestamp, toFiniteNumber } from '@/lib/format'
import type { LearningSummaryView, PipelineStageView } from '@/lib/types'

const PIPELINE_FRESH_WINDOW_MS = 10 * 60 * 1000

interface StreamStat {
  count: number
  lastMessageTimestamp: string | null
}

export function buildLearningSummary(
  streamStats: Record<string, StreamStat>,
  learningEvents: Array<{ type: string }>,
  gradeHistory: GradeRecord[],
  icWeights: Record<string, number>,
  proposals: Proposal[],
  orders: Order[],
): LearningSummaryView {
  const streamReflections = streamStats['reflection_outputs']?.count ?? 0
  const streamEvaluations = streamStats['agent_grades']?.count ?? 0
  const streamIcUpdates = streamStats['factor_ic_history']?.count ?? 0

  const tradesEvaluated = Math.max(
    learningEvents.filter((e) => e?.type === 'trade_evaluated').length,
    streamEvaluations,
    gradeHistory.length,
  )
  const reflectionsCompleted = Math.max(
    learningEvents.filter((e) => e?.type === 'reflection').length,
    streamReflections,
  )
  const icValuesUpdated = Math.max(
    learningEvents.filter((e) => e?.type === 'ic_update').length,
    streamIcUpdates,
    Object.keys(icWeights).length > 0 ? 1 : 0,
  )
  const strategiesTested = Math.max(
    learningEvents.filter((e) => e?.type === 'strategy_tested').length,
    proposals.length,
  )

  const dailyPnlMap = orders.reduce<Record<string, number>>((acc, order) => {
    const ts = parseTimestamp(order?.timestamp)
    if (!ts) return acc
    const key = ts.toDateString()
    acc[key] = (acc[key] ?? 0) + (toFiniteNumber(order?.pnl) ?? 0)
    return acc
  }, {})
  const dayEntries = Object.entries(dailyPnlMap)
  const bestDay = dayEntries.length > 0
    ? dayEntries.reduce((best, current) => (current[1] > best[1] ? current : best))
    : null
  const worstDay = dayEntries.length > 0
    ? dayEntries.reduce((worst, current) => (current[1] < worst[1] ? current : worst))
    : null

  return {
    tradesEvaluated,
    reflectionsCompleted,
    icValuesUpdated,
    strategiesTested,
    bestDay,
    worstDay,
  }
}

export function buildCleanGradeHistory(gradeHistory: GradeRecord[]): GradeRecord[] {
  const seen = new Set<string>()
  return gradeHistory
    .filter((g) => {
      const hasGrade = typeof g.grade === 'string' && g.grade.trim() !== '' && g.grade !== '—'
      const hasScore = typeof g.score_pct === 'number' && Number.isFinite(g.score_pct)
      const hasTime = Boolean(parseTimestamp(g.timestamp))
      return (hasGrade || hasScore) && hasTime
    })
    .sort((a, b) => {
      const aTs = parseTimestamp(a.timestamp)?.getTime() ?? 0
      const bTs = parseTimestamp(b.timestamp)?.getTime() ?? 0
      return bTs - aTs
    })
    .filter((g) => {
      const key = `${g.timestamp}|${g.grade}|${g.score_pct}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

export function buildPipelineStages(
  tradeFeed: TradeFeedItem[],
  cleanGrades: GradeRecord[],
  reflectionsCompleted: number,
  icValuesUpdated: number,
  proposals: Proposal[],
  streamStats: Record<string, StreamStat>,
  now: number = Date.now(),
): readonly PipelineStageView[] {
  const latestTradeTs = tradeFeed
    .map((t) => parseTimestamp(t.filled_at ?? t.created_at))
    .filter((d): d is Date => d instanceof Date)
    .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
  const latestGradeTs = cleanGrades
    .map((g) => parseTimestamp(g.timestamp))
    .filter((d): d is Date => d instanceof Date)
    .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
  const reflectionTs = parseTimestamp(streamStats['reflection_outputs']?.lastMessageTimestamp)
  const proposalTs = proposals
    .map((p) => parseTimestamp(p.timestamp))
    .filter((d): d is Date => d instanceof Date)
    .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
  const icTs = parseTimestamp(streamStats['factor_ic_history']?.lastMessageTimestamp)

  const asStatus = (
    count: number,
    ts: Date | null,
    requiresInput?: number,
  ): 'Active' | 'Idle' | 'Error' => {
    if (count <= 0 && (requiresInput ?? 0) <= 0) return 'Idle'
    if (count <= 0 && (requiresInput ?? 0) > 0) return 'Error'
    if (!ts) return 'Idle'
    return now - ts.getTime() <= PIPELINE_FRESH_WINDOW_MS ? 'Active' : 'Idle'
  }

  return [
    {
      key: 'ingestion',
      label: 'Trade Ingestion',
      count: tradeFeed.length,
      lastRun: latestTradeTs,
      status: asStatus(tradeFeed.length, latestTradeTs),
    },
    {
      key: 'grading',
      label: 'Evaluation & Grading',
      count: cleanGrades.length,
      lastRun: latestGradeTs,
      status: asStatus(cleanGrades.length, latestGradeTs, tradeFeed.length),
    },
    {
      key: 'reflection',
      label: 'Reflection',
      count: reflectionsCompleted,
      lastRun: reflectionTs,
      status: asStatus(reflectionsCompleted, reflectionTs, cleanGrades.length),
    },
    {
      key: 'proposals',
      label: 'Strategy Proposals',
      count: proposals.length,
      lastRun: proposalTs,
      status: asStatus(proposals.length, proposalTs, reflectionsCompleted),
    },
    {
      key: 'ic',
      label: 'IC Updates',
      count: icValuesUpdated,
      lastRun: icTs,
      status: asStatus(icValuesUpdated, icTs, reflectionsCompleted),
    },
  ] as const
}
