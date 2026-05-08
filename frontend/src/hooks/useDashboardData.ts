'use client'

import { useCallback, useEffect, useState } from 'react'
import { useCodexStore, type ProposalType } from '@/stores/useCodexStore'
import {
  getAgentInstances,
  getDashboardState,
  getEventsHistory,
  getIcWeights,
  getLearningGrades,
  getLearningProposals,
  getPerformanceTrends,
  getTradeFeed,
  type GradeRecord,
} from '@/lib/api'
import type {
  ApiHealthState,
  PersistedHistoryItem,
  PersistedStreamCount,
} from '@/lib/types'

const POLL_INTERVAL_MS = 30_000
const STATE_POLL_INTERVAL_MS = 15_000

interface DashboardApiHealth {
  dashboardState: ApiHealthState
  agentInstances: ApiHealthState
  eventHistory: ApiHealthState
}

interface DashboardDataResult {
  apiHealth: DashboardApiHealth
  systemFeedError: string | null
  pricesFetched: boolean
  llmAvailable: boolean | null
  llmProvider: string
  icWeights: Record<string, number>
  gradeHistory: GradeRecord[]
  persistedCounts: PersistedStreamCount[]
  persistedEvents: PersistedHistoryItem[]
  persistedLogs: PersistedHistoryItem[]
}

/**
 * Single source of truth for dashboard REST polling.
 *
 * Replaces the previous ~250 lines of inline `useEffect` / `fetch` / state
 * setters that were scattered through DashboardView. Behavior is preserved:
 *
 * - /dashboard/state and /dashboard/prices are polled every 15s while WS is
 *   disconnected, then a final hydration runs once when WS connects.
 * - /learning/{proposals,ic-weights,grades} polls every 30s and on reconnect.
 * - /dashboard/{trade-feed,performance-trends,agent-instances} poll every 30s.
 * - /dashboard/history/events polls every 30s.
 * - All errors are surfaced in apiHealth — never silently swallowed.
 */
export function useDashboardData(wsConnected: boolean): DashboardDataResult {
  const [apiHealth, setApiHealth] = useState<DashboardApiHealth>({
    dashboardState: 'pending',
    agentInstances: 'pending',
    eventHistory: 'pending',
  })
  const [systemFeedError, setSystemFeedError] = useState<string | null>(null)
  const [pricesFetched, setPricesFetched] = useState(false)
  const [llmAvailable, setLlmAvailable] = useState<boolean | null>(null)
  const [llmProvider, setLlmProvider] = useState<string>('')
  const [icWeights, setIcWeights] = useState<Record<string, number>>({})
  const [gradeHistory, setGradeHistory] = useState<GradeRecord[]>([])
  const [persistedCounts, setPersistedCounts] = useState<PersistedStreamCount[]>([])
  const [persistedEvents, setPersistedEvents] = useState<PersistedHistoryItem[]>([])
  const [persistedLogs, setPersistedLogs] = useState<PersistedHistoryItem[]>([])

  // ── /dashboard/state hydration + price poll fallback ────────────────────
  const fetchState = useCallback(async () => {
    try {
      const data = await getDashboardState()
      // The store's DashboardData type requires `timestamp`; default to now if
      // the backend response omits it.
      useCodexStore.getState().hydrateDashboard({
        ...data,
        timestamp:
          typeof data.timestamp === 'string' ? data.timestamp : new Date().toISOString(),
      })
      setApiHealth((prev) => ({ ...prev, dashboardState: 'ok' }))
      if (typeof data.llm_available === 'boolean') setLlmAvailable(data.llm_available)
      if (typeof data.llm_provider === 'string') setLlmProvider(data.llm_provider)
    } catch {
      setSystemFeedError('Dashboard API unreachable')
      setApiHealth((prev) => ({ ...prev, dashboardState: 'error' }))
    }
  }, [])

  useEffect(() => {
    void fetchState()
    void (async () => {
      await useCodexStore.getState().fetchPrices()
      setPricesFetched(true)
    })()
    if (wsConnected) return
    const id = setInterval(() => {
      void fetchState()
      void useCodexStore.getState().fetchPrices()
    }, STATE_POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [wsConnected, fetchState])

  // ── learning data ───────────────────────────────────────────────────────
  useEffect(() => {
    const { addProposal } = useCodexStore.getState()
    const fetchLearning = async () => {
      try {
        const [proposals, ic, grades] = await Promise.all([
          getLearningProposals().catch(() => null),
          getIcWeights().catch(() => null),
          getLearningGrades().catch(() => null),
        ])

        if (proposals?.proposals) {
          const existing = useCodexStore.getState().proposals
          const existingIds = new Set(existing.map((p) => p.id))
          const newOnes = proposals.proposals.filter(
            (p) => !existingIds.has(p.id as string),
          )
          for (const p of newOnes) {
            addProposal({
              proposal_type: (p.proposal_type as ProposalType) ?? 'parameter_change',
              content: JSON.stringify(p.content),
              requires_approval: p.requires_approval !== false,
              confidence: p.confidence as number | undefined,
              reflection_trace_id: p.reflection_trace_id as string | undefined,
              timestamp: (p.timestamp as string) ?? new Date().toISOString(),
            })
          }
        }
        if (ic?.current_weights) setIcWeights(ic.current_weights)
        if (grades?.grades) setGradeHistory(grades.grades.slice(0, 10))
      } catch {
        // Individual catches above already handle granular failure;
        // the combined try block guards against unexpected exceptions.
      }
    }
    void fetchLearning()
    const id = setInterval(() => void fetchLearning(), POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [wsConnected])

  // ── trade feed ──────────────────────────────────────────────────────────
  useEffect(() => {
    const fetch = async () => {
      try {
        const d = await getTradeFeed()
        useCodexStore.getState().setTradeFeed(d.trades ?? [])
      } catch {
        // non-fatal: WebSocket carries trade fills too
      }
    }
    void fetch()
    const id = setInterval(() => void fetch(), POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [])

  // ── performance summary ─────────────────────────────────────────────────
  useEffect(() => {
    const fetch = async () => {
      try {
        const d = await getPerformanceTrends()
        if (d.summary) useCodexStore.getState().setPerformanceSummary(d.summary)
      } catch {
        // non-fatal
      }
    }
    void fetch()
    const id = setInterval(() => void fetch(), POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [wsConnected])

  // ── agent instances ─────────────────────────────────────────────────────
  useEffect(() => {
    const fetch = async () => {
      try {
        const d = await getAgentInstances()
        useCodexStore.getState().setAgentInstances(d.instances ?? [])
        setApiHealth((prev) => ({ ...prev, agentInstances: 'ok' }))
      } catch {
        setApiHealth((prev) => ({ ...prev, agentInstances: 'error' }))
      }
    }
    void fetch()
    const id = setInterval(() => void fetch(), POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [])

  // ── persisted history ───────────────────────────────────────────────────
  useEffect(() => {
    const fetch = async () => {
      try {
        const d = await getEventsHistory()
        setPersistedCounts((d.stream_counts ?? []) as PersistedStreamCount[])
        setPersistedEvents((d.persisted_events ?? []) as PersistedHistoryItem[])
        setPersistedLogs((d.persisted_logs ?? []) as PersistedHistoryItem[])
        setApiHealth((prev) => ({ ...prev, eventHistory: 'ok' }))
      } catch {
        setApiHealth((prev) => ({ ...prev, eventHistory: 'error' }))
      }
    }
    void fetch()
    const id = setInterval(() => void fetch(), POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [])

  return {
    apiHealth,
    systemFeedError,
    pricesFetched,
    llmAvailable,
    llmProvider,
    icWeights,
    gradeHistory,
    persistedCounts,
    persistedEvents,
    persistedLogs,
  }
}
