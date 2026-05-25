'use client'

import { useEffect, useState } from 'react'
import { useCodexStore, type ProposalType } from '@/stores/useCodexStore'
import { api, API_ENDPOINTS } from '@/lib/apiClient'

export interface ApiHealth {
  dashboardState: 'pending' | 'ok' | 'error'
  agentInstances: 'pending' | 'ok' | 'error'
  eventHistory: 'pending' | 'ok' | 'error'
}

export interface PersistedStreamCount {
  stream: string
  processed_count: number
  last_processed_at: string | null
}

export interface PersistedHistoryItem {
  id: string
  kind: string
  source?: string | null
  trace_id?: string | null
  created_at: string | null
}

export interface DecisionStats {
  total: number
  last_hour: { buys: number; sells: number; holds: number }
  last_decision: Record<string, unknown> | null
}

interface TradeFeedUpstream {
  signal_events?: number
  decisions_evaluated?: number
  ee_last_status?: string | null
  ee_event_count?: number
}

export interface RestPollState {
  apiHealth: ApiHealth
  systemFeedError: string | null
  llmAvailable: boolean | null
  llmProvider: string
  pricesFetched: boolean
  tradeFeedEmptyReason: string | null
  tradeFeedUpstream: TradeFeedUpstream | null
  decisionStats: DecisionStats | null
  recentDecisions: Array<Record<string, unknown>>
  persistedCounts: PersistedStreamCount[]
  persistedEvents: PersistedHistoryItem[]
  persistedLogs: PersistedHistoryItem[]
}

export function useRestPoll(wsConnected: boolean): RestPollState {
  const [apiHealth, setApiHealth] = useState<ApiHealth>({
    dashboardState: 'pending',
    agentInstances: 'pending',
    eventHistory: 'pending',
  })
  const [systemFeedError, setSystemFeedError] = useState<string | null>(null)
  const [llmAvailable, setLlmAvailable] = useState<boolean | null>(null)
  const [llmProvider, setLlmProvider] = useState<string>('')
  const [pricesFetched, setPricesFetched] = useState(false)
  const [tradeFeedEmptyReason, setTradeFeedEmptyReason] = useState<string | null>(null)
  const [tradeFeedUpstream, setTradeFeedUpstream] = useState<TradeFeedUpstream | null>(null)
  const [decisionStats, setDecisionStats] = useState<DecisionStats | null>(null)
  const [recentDecisions, setRecentDecisions] = useState<Array<Record<string, unknown>>>([])
  const [persistedCounts, setPersistedCounts] = useState<PersistedStreamCount[]>([])
  const [persistedEvents, setPersistedEvents] = useState<PersistedHistoryItem[]>([])
  const [persistedLogs, setPersistedLogs] = useState<PersistedHistoryItem[]>([])

  // ── Dashboard state + prices ────────────────────────────────────────────────
  useEffect(() => {
    const fetchDashboardState = async () => {
      try {
        const res = await fetch(api('/dashboard/state'))
        if (res.ok) {
          const data = await res.json()
          useCodexStore.getState().hydrateDashboard(data)
          setApiHealth((prev) => ({ ...prev, dashboardState: 'ok' }))
          if (typeof data.llm_available === 'boolean') setLlmAvailable(data.llm_available)
          if (typeof data.llm_provider === 'string') setLlmProvider(data.llm_provider)
        } else {
          setApiHealth((prev) => ({ ...prev, dashboardState: 'error' }))
        }
      } catch {
        setSystemFeedError('Dashboard API unreachable')
        setApiHealth((prev) => ({ ...prev, dashboardState: 'error' }))
      }
    }

    const fetchPrices = async () => {
      await useCodexStore.getState().fetchPrices()
      setPricesFetched(true)
    }

    fetchDashboardState()
    fetchPrices()

    const cadenceMs = wsConnected ? 30_000 : 15_000
    const t = setInterval(() => {
      fetchDashboardState()
      useCodexStore.getState().fetchPrices()
    }, cadenceMs)
    return () => clearInterval(t)
  }, [wsConnected])

  // ── Learning data (proposals, IC weights, grades) ──────────────────────────
  useEffect(() => {
    const fetchLearning = async () => {
      try {
        const res = await fetch(api(API_ENDPOINTS.LEARNING_PROPOSALS))
        if (!res.ok) return
        const data = await res.json()
        const { addProposal, proposals: existing } = useCodexStore.getState()
        const existingIds = new Set(existing.map((p) => p.id))
        const newOnes = (data.proposals ?? []).filter(
          (p: Record<string, unknown>) => !existingIds.has(p.id as string),
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
      } catch {
        // non-fatal
      }
    }

    fetchLearning()
    const t = setInterval(fetchLearning, 30_000)
    return () => clearInterval(t)
  }, [wsConnected])

  // ── Trade feed ─────────────────────────────────────────────────────────────
  useEffect(() => {
    const fetchTradeFeed = async () => {
      try {
        const res = await fetch(api(API_ENDPOINTS.DASHBOARD_TRADE_FEED))
        if (!res.ok) return
        const d = await res.json()
        const trades = d.trades ?? []
        useCodexStore.getState().setTradeFeed(trades)
        if (trades.length === 0) {
          setTradeFeedEmptyReason(d.empty_reason ?? null)
          setTradeFeedUpstream(d.upstream_activity ?? null)
        } else {
          setTradeFeedEmptyReason(null)
          setTradeFeedUpstream(null)
        }
      } catch {
        // non-fatal
      }
    }

    fetchTradeFeed()
    const t = setInterval(fetchTradeFeed, 30_000)
    return () => clearInterval(t)
  }, [])

  // ── Notifications (Redis-backed, works in memory mode) ─────────────────────
  useEffect(() => {
    const fetchNotifications = async () => {
      try {
        const res = await fetch(api(API_ENDPOINTS.NOTIFICATIONS_RECENT))
        if (!res.ok) return
        const items = (await res.json()) as Array<Record<string, unknown>>
        const { addNotification } = useCodexStore.getState()
        for (const raw of [...items].reverse()) {
          addNotification({ ...raw, stream_source: raw.stream_source ?? 'rest' })
        }
      } catch {
        // non-fatal
      }
    }

    fetchNotifications()
    const t = setInterval(fetchNotifications, 30_000)
    return () => clearInterval(t)
  }, [wsConnected])

  // ── Decisions (stats + recent list) ────────────────────────────────────────
  useEffect(() => {
    const fetchDecisions = async () => {
      try {
        const [statsRes, recentRes] = await Promise.all([
          fetch(api(API_ENDPOINTS.DECISIONS_STATS)),
          fetch(api(`${API_ENDPOINTS.DECISIONS_RECENT}?limit=20`)),
        ])
        if (statsRes.ok) setDecisionStats(await statsRes.json())
        if (recentRes.ok) setRecentDecisions(await recentRes.json())
      } catch {
        // non-fatal
      }
    }

    fetchDecisions()
    const t = setInterval(fetchDecisions, 15_000)
    return () => clearInterval(t)
  }, [wsConnected])

  // ── Performance summary ────────────────────────────────────────────────────
  useEffect(() => {
    const fetchPerformance = async () => {
      try {
        const res = await fetch(api(API_ENDPOINTS.DASHBOARD_PERFORMANCE_TRENDS))
        if (!res.ok) return
        const d = await res.json()
        if (d.summary) useCodexStore.getState().setPerformanceSummary(d.summary)
      } catch {
        // non-fatal
      }
    }

    fetchPerformance()
    const t = setInterval(fetchPerformance, 30_000)
    return () => clearInterval(t)
  }, [wsConnected])

  // ── Agent instances + persisted event history ──────────────────────────────
  useEffect(() => {
    const fetchAgentInstances = async () => {
      try {
        const res = await fetch(api(API_ENDPOINTS.DASHBOARD_AGENT_INSTANCES))
        if (!res.ok) {
          setApiHealth((prev) => ({ ...prev, agentInstances: 'error' }))
          return
        }
        const d = await res.json()
        useCodexStore.getState().setAgentInstances(d.instances ?? [])
        setApiHealth((prev) => ({ ...prev, agentInstances: 'ok' }))
      } catch {
        setApiHealth((prev) => ({ ...prev, agentInstances: 'error' }))
      }
    }

    const fetchPersistedHistory = async () => {
      try {
        const res = await fetch(api(API_ENDPOINTS.EVENTS_HISTORY))
        if (!res.ok) {
          setApiHealth((prev) => ({ ...prev, eventHistory: 'error' }))
          return
        }
        const d = await res.json()
        setPersistedCounts((d.stream_counts ?? []) as PersistedStreamCount[])
        setPersistedEvents((d.persisted_events ?? []) as PersistedHistoryItem[])
        setPersistedLogs((d.persisted_logs ?? []) as PersistedHistoryItem[])
        setApiHealth((prev) => ({ ...prev, eventHistory: 'ok' }))
      } catch {
        setApiHealth((prev) => ({ ...prev, eventHistory: 'error' }))
      }
    }

    fetchAgentInstances()
    fetchPersistedHistory()
    const t1 = setInterval(fetchAgentInstances, 30_000)
    const t2 = setInterval(fetchPersistedHistory, 30_000)
    return () => {
      clearInterval(t1)
      clearInterval(t2)
    }
  }, [])

  return {
    apiHealth,
    systemFeedError,
    llmAvailable,
    llmProvider,
    pricesFetched,
    tradeFeedEmptyReason,
    tradeFeedUpstream,
    decisionStats,
    recentDecisions,
    persistedCounts,
    persistedEvents,
    persistedLogs,
  }
}
