'use client'

import { useCallback, useEffect, useMemo, useState, type ComponentType } from 'react'
import { useCodexStore, type AgentStatus, type ProposalType } from '@/stores/useCodexStore'
import { api, API_ENDPOINTS } from '@/lib/apiClient'
import { cn } from '@/lib/utils'
import { EquityCurve } from '@/components/dashboard/EquityCurve'
import { AgentStream } from '@/components/dashboard/AgentStream'
import { PositionsTable } from '@/components/dashboard/PositionsTable'
import {
  Activity,
  Bell,
  Brain,
  CheckCheck,
  FileCode,
  ThumbsDown,
  ThumbsUp,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react'
import type { Notification, Proposal } from '@/stores/useCodexStore'

const sanitizeValue = (value: string | number | boolean | null | undefined): string => {
  if (value === undefined || value === null || value === '') return '--';
  if (typeof value === 'number' && (isNaN(value) || !isFinite(value))) return '--';
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  return String(value);
};

const toSanitizeInput = (value: unknown): string | number | boolean | null | undefined => {
  if (value === null || value === undefined) return value
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value
  return String(value)
}

// Map internal reasoning fallback markers to human-readable text for the
// Agent Thought Stream. The backend writes `primary_edge = "fallback:<mode>"`
// whenever the LLM is unavailable; the raw token is ugly in the UI.
const FALLBACK_LABELS: Record<string, string> = {
  skip_reasoning: 'Rule-based fallback decision',
  reject_signal: 'Rule-based fallback: signal rejected',
  use_last_reflection: 'Rule-based fallback: reused last reflection',
}
const formatAgentMessage = (raw: unknown): string => {
  const text = sanitizeValue(toSanitizeInput(raw))
  if (text === '--') return 'N/A'
  if (text.startsWith('fallback:')) {
    const mode = text.slice('fallback:'.length)
    return FALLBACK_LABELS[mode] ?? 'LLM unavailable'
  }
  return text
}

const formatUSD = (value?: number | null): string => {
  if (value == null || isNaN(value) || !isFinite(value)) return '$0.00';
  return `$${Math.abs(value).toFixed(2)}`;
};

const formatTimeAgo = (date: Date): string => {
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
};

const formatTimestamp = (value?: string | null): string => {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleTimeString()
}

const formatAgeFromMs = (ageMs: number | null): string => {
  if (ageMs == null || ageMs < 0 || !Number.isFinite(ageMs)) return '--'
  const sec = Math.floor(ageMs / 1000)
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m`
  const hr = Math.floor(min / 60)
  return `${hr}h`
}

const formatWiringAge = (ageMs: number | null): string => {
  const age = formatAgeFromMs(ageMs)
  return age === '--' ? 'No recent timestamp' : `last ${age} ago`
}

const cardClass = 'rounded-xl border border-slate-200 bg-white p-4 transition-colors duration-150 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-600 sm:p-5'
const sectionTitleClass = 'text-xs font-semibold uppercase tracking-widest font-sans text-slate-500 dark:text-slate-400'
const mutedClass = 'text-xs font-sans text-slate-500 dark:text-slate-400'
const valueClass = 'text-2xl font-black font-mono tabular-nums text-slate-950 dark:text-slate-100'

type Section = 'overview' | 'trading' | 'agents' | 'learning' | 'proposals' | 'system'
type SystemStatus = 'booting' | 'idle' | 'trading' | 'error'

type AgentSummary = {
  name: string
  realtimeCount: number
  persistedCount: number
  lastSeen: Date | null
  status: 'Live' | 'Stale' | 'Error' | 'Idle'
  tier: 'active' | 'challenger' | 'inactive'
  source: 'realtime' | 'persisted' | 'hybrid'
}

type PersistedStreamCount = {
  stream: string
  processed_count: number
  last_processed_at: string | null
}

type PersistedHistoryItem = {
  id: string
  kind: string
  source?: string | null
  trace_id?: string | null
  created_at: string | null
}

function displayAgentName(rawName: string): string {
  const canonical = canonicalAgentKey(rawName)
  if (canonical === 'IC_UPDATER') return 'Indicator Cache Updater'
  return rawName
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .trim()
    .toLowerCase()
    .replace(/\b\w/g, (m) => m.toUpperCase())
}

const TICKER_SYMBOLS = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'AAPL', 'TSLA', 'SPY'] as const
const AGENT_LIVE_THRESHOLD_MS = 10_000
const AGENT_STALE_THRESHOLD_MS = 120_000

function toFiniteNumber(value: unknown): number | null {
  const cast = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(cast) ? cast : null
}

function isClosedTrade(order: Record<string, unknown> | null | undefined): boolean {
  if (!order) return false
  const status = String(order.status ?? '').toLowerCase()
  if (status === 'filled' || status === 'closed' || status === 'executed' || status === 'completed') return true
  if (order.filled_at != null) return true
  return false
}

function parseTimestamp(value: unknown): Date | null {
  if (value == null) return null
  if (value instanceof Date && !Number.isNaN(value.getTime())) return value
  if (typeof value === 'number') {
    const ms = value > 10_000_000_000 ? value : value * 1000
    const d = new Date(ms)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const raw = String(value).trim()
  if (!raw) return null
  if (/^\d+(\.\d+)?$/.test(raw)) {
    const num = Number(raw)
    if (Number.isFinite(num)) {
      const ms = num > 10_000_000_000 ? num : num * 1000
      const d = new Date(ms)
      if (!Number.isNaN(d.getTime())) return d
    }
  }
  const d = new Date(raw)
  return Number.isNaN(d.getTime()) ? null : d
}

function parseHeartbeatTimestamp(status: AgentStatus): Date | null {
  const fromIsoField = parseTimestamp(status.last_seen_at)
  if (fromIsoField) return fromIsoField
  const fromEpochField = parseTimestamp(status.last_seen)
  if (fromEpochField) return fromEpochField
  // Backward compatibility for older payloads that (incorrectly) used last_event as a timestamp.
  return parseTimestamp(status.last_event)
}

function canonicalAgentKey(name: string): string {
  return name.trim().toUpperCase().replace(/[\s-]+/g, '_')
}

function formatAgentSource(source: AgentSummary['source']): string {
  if (source === 'realtime') return 'Realtime'
  if (source === 'persisted') return 'Persisted'
  return 'Hybrid'
}

function pickHigherPriorityStatus(
  current: AgentSummary['status'] | undefined,
  incoming: AgentSummary['status'],
): AgentSummary['status'] {
  if (!current) return incoming
  const priority: Record<AgentSummary['status'], number> = {
    Live: 0,
    Stale: 1,
    Error: 2,
    Idle: 3,
  }
  return priority[incoming] < priority[current] ? incoming : current
}

function getMetric(systemMetrics: Array<Record<string, unknown>>, metricName: string): number | null {
  const match = systemMetrics.find((metric) => metric?.metric_name === metricName)
  return toFiniteNumber(match?.value)
}

function EmptyState({ message }: { message: string; icon?: ComponentType<{ className?: string }> }) {
  return (
    <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed border-slate-300 px-4 py-10 dark:border-slate-700">
      <p className="text-sm font-sans text-slate-400">{message}</p>
    </div>
  )
}

function PriceCardSkeleton() {
  return (
    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <div className="mb-1 h-3 w-16 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      <div className="mt-1 h-6 w-24 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      <div className="mt-2 flex items-center justify-between">
        <div className="h-3 w-16 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
        <div className="h-3 w-12 animate-pulse rounded bg-slate-200 dark:bg-slate-700" />
      </div>
    </div>
  )
}

const SEVERITY_STYLES: Record<string, { badge: string; dot: string; label: string }> = {
  CRITICAL: { badge: 'bg-rose-500/15 text-rose-500 border border-rose-500/30', dot: 'bg-rose-500 animate-pulse', label: 'CRITICAL' },
  URGENT: { badge: 'bg-orange-500/15 text-orange-500 border border-orange-500/30', dot: 'bg-orange-500', label: 'URGENT' },
  WARNING: { badge: 'bg-amber-500/15 text-amber-500 border border-amber-500/30', dot: 'bg-amber-400', label: 'WARNING' },
  INFO: { badge: 'bg-slate-500/10 text-slate-500 border border-slate-500/30', dot: 'bg-slate-400', label: 'INFO' },
}

function NotificationFeed({
  notifications,
  wsConnected,
  onAcknowledge,
}: {
  notifications: Notification[]
  wsConnected: boolean
  onAcknowledge: (id: string) => void
}) {
  const unread = notifications.filter((n) => !n.acknowledged)
  return (
    <div className={cardClass}>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell className="h-4 w-4 text-slate-500" />
          <p className={sectionTitleClass}>Notifications</p>
        </div>
        <div className="flex items-center gap-2">
          {unread.length > 0 && (
            <span className="rounded-full bg-rose-500 px-2 py-0.5 text-xs font-bold text-white">{unread.length}</span>
          )}
          <p className={mutedClass}>{notifications.length} total</p>
        </div>
      </div>
      {notifications.length === 0 ? (
        <EmptyState message={wsConnected ? 'No notifications yet' : 'Stream disconnected'} />
      ) : (
        <div className="max-h-72 space-y-2 overflow-y-auto">
          {notifications.map((notif) => {
            const style = SEVERITY_STYLES[notif.severity] ?? SEVERITY_STYLES['INFO']
            return (
              <div
                key={notif.id}
                className={cn(
                  'flex items-start gap-3 rounded-lg border px-3 py-2.5 transition-opacity',
                  notif.acknowledged ? 'border-slate-200 opacity-50 dark:border-slate-800' : 'border-slate-200 dark:border-slate-800',
                )}
              >
                <span className={cn('mt-1.5 h-2 w-2 shrink-0 rounded-full', style.dot)} />
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-center gap-2">
                    <span className={cn('rounded px-1.5 py-0.5 text-xs font-bold', style.badge)}>{style.label}</span>
                    <span className={mutedClass}>{sanitizeValue(notif.notification_type)}</span>
                    <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide', notif.state === 'resolved' || notif.acknowledged ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500')}>
                      {notif.state === 'resolved' || notif.acknowledged ? 'resolved' : 'action needed'}
                    </span>
                    <span className={cn(mutedClass, 'ml-auto shrink-0')}>{formatTimestamp(notif.timestamp)}</span>
                  </div>
                  <p className="text-sm font-sans text-slate-700 dark:text-slate-300">{sanitizeValue(notif.message) === '--' ? 'No message' : notif.message}</p>
                  <p className={cn(mutedClass, 'mt-1')}>
                    Source: {sanitizeValue(notif.stream_source) === '--' ? 'system' : sanitizeValue(notif.stream_source)}
                    {notif.trace_id ? ` · Trace ${notif.trace_id.slice(0, 8)}` : ''}
                  </p>
                </div>
                {!notif.acknowledged && (
                  <button
                    onClick={() => onAcknowledge(notif.id)}
                    className="mt-0.5 shrink-0 rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-emerald-500 dark:hover:bg-slate-800"
                    title="Acknowledge"
                  >
                    <CheckCheck className="h-4 w-4" />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

const PROPOSAL_TYPE_LABEL: Record<string, string> = {
  parameter_change: 'Param Change',
  code_change: 'Code Change',
  regime_adjustment: 'Regime Adjust',
}
const PROPOSAL_TYPE_STYLE: Record<string, string> = {
  parameter_change: 'bg-slate-500/10 text-slate-500',
  code_change: 'bg-slate-500/10 text-slate-500',
  regime_adjustment: 'bg-amber-500/15 text-amber-500',
}

function ProposalsFeed({
  proposals,
  onUpdateStatus,
}: {
  proposals: Proposal[]
  onUpdateStatus: (id: string, status: import('@/stores/useCodexStore').ProposalStatus) => void
}) {
  const pending = proposals.filter((p) => p.status === 'pending')
  return (
    <div className={cardClass}>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-slate-500" />
          <p className={sectionTitleClass}>Strategy Proposals</p>
        </div>
        <div className="flex items-center gap-2">
          {pending.length > 0 && (
            <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-bold text-slate-900 dark:bg-slate-700 dark:text-slate-100">{pending.length} pending</span>
          )}
          <p className={mutedClass}>{proposals.length} total</p>
        </div>
      </div>
      {proposals.length === 0 ? (
        <EmptyState message="No proposals yet" icon={Brain} />
      ) : (
        <div className="max-h-96 space-y-3 overflow-y-auto">
          {proposals.map((proposal) => (
            <div
              key={proposal.id}
              className={cn(
                'rounded-lg border p-3 transition-opacity',
                proposal.status === 'pending' ? 'border-slate-200 dark:border-slate-800/50' : 'border-slate-200 opacity-60 dark:border-slate-800',
              )}
            >
              <div className="mb-2 flex items-center gap-2 flex-wrap">
                <span className={cn('rounded px-2 py-0.5 text-xs font-bold', PROPOSAL_TYPE_STYLE[proposal.proposal_type] ?? 'bg-slate-500/15 text-slate-400')}>
                  {PROPOSAL_TYPE_LABEL[proposal.proposal_type] ?? proposal.proposal_type}
                </span>
                {proposal.confidence != null && (
                  <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-500 dark:bg-slate-800">
                    {(proposal.confidence * 100).toFixed(0)}% confidence
                  </span>
                )}
                {proposal.status !== 'pending' && (
                  <span className={cn('rounded px-2 py-0.5 text-xs font-semibold', proposal.status === 'approved' ? 'bg-emerald-500/15 text-emerald-500' : 'bg-rose-500/15 text-rose-500')}>
                    {proposal.status}
                  </span>
                )}
                <span className={cn(mutedClass, 'ml-auto')}>{formatTimestamp(proposal.timestamp)}</span>
              </div>
              <p className="mb-2 text-sm font-sans leading-relaxed text-slate-700 dark:text-slate-300">
                {sanitizeValue(proposal.content) === '--' ? 'No description' : proposal.content}
              </p>
              {proposal.status === 'pending' && proposal.requires_approval && (
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => onUpdateStatus(proposal.id, 'approved')}
                    className="flex items-center gap-1.5 rounded-lg bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-600 transition-colors hover:bg-emerald-500/20 dark:text-emerald-400"
                  >
                    <ThumbsUp className="h-3 w-3" />
                    Approve
                  </button>
                  <button
                    onClick={() => onUpdateStatus(proposal.id, 'rejected')}
                    className="flex items-center gap-1.5 rounded-lg bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-600 transition-colors hover:bg-rose-500/20 dark:text-rose-400"
                  >
                    <ThumbsDown className="h-3 w-3" />
                    Reject
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Trace modal
// ---------------------------------------------------------------------------

type TraceData = {
  trace_id: string
  agent_runs: Array<Record<string, unknown>>
  agent_logs: Array<Record<string, unknown>>
  agent_grades: Array<Record<string, unknown>>
}

function TraceModal({ traceId, onClose }: { traceId: string; onClose: () => void }) {
  const [data, setData] = useState<TraceData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(api(`/dashboard/trace/${encodeURIComponent(traceId)}`))
      .then((r) => r.json())
      .then((d) => { setData(d as TraceData); setLoading(false) })
      .catch(() => { setError('Failed to load trace'); setLoading(false) })
  }, [traceId])

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-16" onClick={onClose}>
      <div
        className="w-full max-w-3xl overflow-y-auto rounded-xl border border-slate-200 bg-white p-5 shadow-2xl dark:border-slate-700 dark:bg-slate-900 max-h-[80vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <p className={cn(sectionTitleClass)}>Trace: <span className="font-mono text-slate-700 dark:text-slate-300">{traceId.slice(0, 16)}…</span></p>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 text-xl font-bold leading-none">×</button>
        </div>
        {loading && <p className={mutedClass}>Loading…</p>}
        {error && <p className="text-rose-500 text-sm">{error}</p>}
        {data && (
          <div className="space-y-4">
            {data.agent_runs.length > 0 && (
              <div>
                <p className={cn(sectionTitleClass, 'mb-2')}>Agent Runs</p>
                <div className="space-y-1">
                  {data.agent_runs.map((r, i) => (
                    <div key={i} className="rounded border border-slate-200 dark:border-slate-700 p-2 text-xs font-mono text-slate-700 dark:text-slate-300">
                      <span className="font-bold text-slate-900 dark:text-slate-100">{String(r.agent_name ?? '--')}</span>
                      {' · '}{String(r.run_type ?? '')} · {String(r.status ?? '')}
                      {r.execution_time_ms != null && <span className={mutedClass}> · {String(r.execution_time_ms)}ms</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {data.agent_logs.length > 0 && (
              <div>
                <p className={cn(sectionTitleClass, 'mb-2')}>Agent Logs</p>
                <div className="space-y-1">
                  {data.agent_logs.map((lg, i) => (
                    <div key={i} className="rounded border border-slate-200 dark:border-slate-700 p-2 text-xs font-mono text-slate-700 dark:text-slate-300">
                      <span className="text-slate-500">{String(lg.log_type ?? '--')}</span>
                      {' · '}{String(lg.created_at ?? '')}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {data.agent_grades.length > 0 && (
              <div>
                <p className={cn(sectionTitleClass, 'mb-2')}>Grades</p>
                <div className="space-y-1">
                  {data.agent_grades.map((g, i) => {
                    const score = typeof g.score === 'number' ? g.score : null
                    const scoreColor = score == null ? 'text-slate-400' : score >= 70 ? 'text-emerald-500' : score >= 40 ? 'text-amber-500' : 'text-rose-500'
                    return (
                      <div key={i} className="rounded border border-slate-200 dark:border-slate-700 p-2 text-xs font-mono text-slate-700 dark:text-slate-300 flex items-center gap-2">
                        <span>{String(g.grade_type ?? '--')}</span>
                        <span className={cn('font-bold', scoreColor)}>{score == null ? '--' : score.toFixed(1)}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Proposals section
// ---------------------------------------------------------------------------

function ProposalsSection() {
  const proposals = useCodexStore((state) => state.proposals)
  const updateProposalStatus = useCodexStore((state) => state.updateProposalStatus)
  const [pendingAction, setPendingAction] = useState<string | null>(null)

  const handleVote = async (id: string, vote: 'approve' | 'reject') => {
    setPendingAction(id)
    const status = vote === 'approve' ? 'approved' as const : 'rejected' as const
    try {
      await fetch(api(`/dashboard/learning/proposals/${encodeURIComponent(id)}`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      updateProposalStatus(id, status)
    } catch {
      // non-fatal — store will update optimistically
      updateProposalStatus(id, status)
    } finally {
      setPendingAction(null)
    }
  }

  if (proposals.length === 0) {
    return (
      <div className={cardClass}>
        <p className={cn(sectionTitleClass, 'mb-3')}>Strategy Proposals</p>
        <EmptyState message="No proposals yet — they arrive from the ReflectionAgent" icon={Zap} />
      </div>
    )
  }

  return (
    <div className={cardClass}>
      <p className={cn(sectionTitleClass, 'mb-3')}>Strategy Proposals</p>
      <div className="space-y-3">
        {proposals.map((p) => {
          const isPending = p.status === 'pending'
          const isApproved = p.status === 'approved'
          const confidencePct = p.confidence != null ? `${(p.confidence * 100).toFixed(0)}%` : null
          return (
            <div
              key={p.id}
              className={cn(
                'rounded-lg border p-3',
                isApproved ? 'border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/30' :
                p.status === 'rejected' ? 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/30 opacity-60' :
                'border-slate-200 dark:border-slate-800'
              )}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-1 min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="rounded bg-slate-500/10 px-2 py-0.5 text-xs font-semibold text-slate-500">
                      {p.proposal_type.replace(/_/g, ' ')}
                    </span>
                    {confidencePct && <span className={mutedClass}>{confidencePct} confidence</span>}
                  </div>
                  <p className="text-sm text-slate-700 dark:text-slate-300 leading-snug line-clamp-3">{p.content || '--'}</p>
                  {p.reflection_trace_id && (
                    <p className="text-[10px] font-mono text-slate-400 truncate">trace: {p.reflection_trace_id.slice(0, 16)}…</p>
                  )}
                </div>
                {isPending ? (
                  <div className="flex gap-2 shrink-0">
                    <button
                      disabled={pendingAction === p.id}
                      onClick={() => handleVote(p.id, 'approve')}
                      className="rounded px-3 py-1 text-xs font-semibold bg-emerald-500 text-white hover:bg-emerald-600 disabled:opacity-50"
                    >Approve</button>
                    <button
                      disabled={pendingAction === p.id}
                      onClick={() => handleVote(p.id, 'reject')}
                      className="rounded px-3 py-1 text-xs font-semibold bg-rose-500 text-white hover:bg-rose-600 disabled:opacity-50"
                    >Reject</button>
                  </div>
                ) : (
                  <span className={cn('shrink-0 rounded px-2 py-1 text-xs font-semibold',
                    isApproved ? 'bg-emerald-500/15 text-emerald-600' : 'bg-slate-500/15 text-slate-500'
                  )}>{p.status}</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return `${hours}h ${remainingMinutes}m`
}

export function DashboardView({ section }: { section: Section }) {
  const {
    agentLogs = [],
    learningEvents = [],
    orders = [],
    prices = {},
    positions = [],
    systemMetrics = [],
    notifications = [],
    proposals = [],
    tradeFeed = [],
    agentInstances = [],
    performanceSummary,
    dashboardData,
    wsConnected,
    marketTickCount,
    lastMarketSymbol,
    streamStats,
    wsMessageCount,
    wsLastMessageTimestamp,
    wsDiagnostics,
    recentEvents = [],
    agentStatuses = [],
    acknowledgeNotification,
    updateProposalStatus,
  } = useCodexStore()

  const [activeTraceId, setActiveTraceId] = useState<string | null>(null)
  const [showNoAgentDataMessage, setShowNoAgentDataMessage] = useState(false)
  const [icWeights, setIcWeights] = useState<Record<string, number>>({})
  const [gradeHistory, setGradeHistory] = useState<Array<{ grade: string; score_pct: number; timestamp: string }>>([])
  // Track whether we have attempted a price fetch so we stop showing skeleton
  // loaders even when the price poller hasn't populated Redis yet.
  const [pricesFetched, setPricesFetched] = useState(false)
  const [persistedCounts, setPersistedCounts] = useState<PersistedStreamCount[]>([])
  const [persistedEvents, setPersistedEvents] = useState<PersistedHistoryItem[]>([])
  const [persistedLogs, setPersistedLogs] = useState<PersistedHistoryItem[]>([])
  const [apiHealth, setApiHealth] = useState<{
    dashboardState: 'pending' | 'ok' | 'error'
    agentInstances: 'pending' | 'ok' | 'error'
    eventHistory: 'pending' | 'ok' | 'error'
  }>({
    dashboardState: 'pending',
    agentInstances: 'pending',
    eventHistory: 'pending',
  })
  const [systemFeedError, setSystemFeedError] = useState<string | null>(null)

  // Show skeletons only on the very first render before we've attempted a fetch.
  // Once we've tried (success or failure) show real cards so the UI doesn't
  // get stuck in skeleton mode when the price poller hasn't run yet.
  const pricesLoading = !pricesFetched && Object.keys(prices).length === 0
  const latestTickTs = streamStats['market_ticks']?.lastMessageTimestamp ?? null
  const dataLatencyMs = latestTickTs ? Math.max(Date.now() - new Date(latestTickTs).getTime(), 0) : null
  const wsLatencyMs = wsLastMessageTimestamp ? Math.max(Date.now() - new Date(wsLastMessageTimestamp).getTime(), 0) : null
  const recentEventLatencyMs = recentEvents.length > 0 && recentEvents[0]?.timestamp
    ? Math.max(Date.now() - new Date(recentEvents[0].timestamp).getTime(), 0)
    : null
  const effectiveLatencyMs = dataLatencyMs ?? wsLatencyMs ?? recentEventLatencyMs
  const throughput = Number(wsDiagnostics?.messageRate ?? 0)
  const pipelineStatus = !latestTickTs
    ? 'Stalled'
    : dataLatencyMs != null && dataLatencyMs < 15_000
      ? 'Healthy'
      : 'Degraded'
  const signalsCount = streamStats['signals']?.count ?? 0
  const ordersCount = streamStats['orders']?.count ?? 0
  const executionsCount = streamStats['executions']?.count ?? 0
  const pipelineWarning = signalsCount > 0 && ordersCount === 0
  const hasMarketData = Boolean(
    latestTickTs
    || (streamStats['market_ticks']?.count ?? 0) > 0
    || recentEvents.some((event) => event.stream === 'market_ticks' || event.stream === 'market_events'),
  )
  const isInMemoryMode = String((dashboardData as Record<string, unknown> | null)?.mode ?? '').includes('in_memory')
  const persistenceEnabled = Boolean(
    isInMemoryMode || persistedCounts.length > 0 || persistedEvents.length > 0 || persistedLogs.length > 0 || apiHealth.eventHistory === 'ok',
  )
  const signalAgentRealtimeCount = agentStatuses.find((agent) => canonicalAgentKey(agent.name) === 'SIGNAL_AGENT')?.event_count ?? 0
  const reasoningAgentStatus = agentStatuses.find((agent) => canonicalAgentKey(agent.name) === 'REASONING_AGENT')?.status ?? 'unknown'
  const executionAgentStatus = agentStatuses.find((agent) => canonicalAgentKey(agent.name) === 'EXECUTION_ENGINE')?.status ?? 'unknown'
  const realizedPnl = tradeFeed.reduce((sum, row) => sum + (row.pnl ?? 0), 0)
  const unrealizedPnl = positions.reduce((sum, row) => sum + (toFiniteNumber((row as Record<string, unknown>).pnl) ?? 0), 0)
  const totalTrades = tradeFeed.filter((row) => row.pnl != null).length
  const wins = tradeFeed.filter((row) => (row.pnl ?? 0) > 0).length
  const pnlWinRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0
  const systemStatus = useMemo<SystemStatus>(() => {
    if (systemFeedError) return 'error'
    const marketConnected = wsConnected || (dataLatencyMs != null && dataLatencyMs <= 5_000)
    if (!marketConnected) return 'booting'
    if (positions.length === 0 && (streamStats.executions?.count ?? 0) === 0) return 'idle'
    if (positions.length > 0 || orders.length > 0 || tradeFeed.length > 0) return 'trading'
    return 'idle'
  }, [dataLatencyMs, orders.length, positions.length, streamStats.executions?.count, systemFeedError, tradeFeed.length, wsConnected])

  // ── REST fallback data fetching ──────────────────────────────────────────
  // Poll /dashboard/state and /dashboard/prices while the WebSocket is not yet
  // connected. Stops as soon as wsConnected flips to true (WS takes over).
  // This is the primary defence against Render cold-starts, misconfigured WS
  // URL env vars, and any brief network hiccup on first load.
  useEffect(() => {
    const fetchState = async () => {
      try {
        console.info('[Dashboard] REST fetch /dashboard/state (wsConnected:', wsConnected, ')')
        const r = await fetch(api('/dashboard/state'))
        if (r.ok) {
          const data = await r.json()
          console.info('[Dashboard] /dashboard/state OK — orders:', data.orders?.length ?? 0, 'positions:', data.positions?.length ?? 0, 'agent_logs:', data.agent_logs?.length ?? 0)
          useCodexStore.getState().hydrateDashboard(data)
          setApiHealth((prev) => ({ ...prev, dashboardState: 'ok' }))
        } else {
          console.warn('[Dashboard] /dashboard/state responded', r.status)
          setApiHealth((prev) => ({ ...prev, dashboardState: 'error' }))
        }
      } catch (err) {
        console.warn('[Dashboard] /dashboard/state fetch failed:', err)
        setSystemFeedError('Dashboard API unreachable')
        setApiHealth((prev) => ({ ...prev, dashboardState: 'error' }))
      }
    }
    const fetchPricesOnce = async () => {
      console.info('[Dashboard] Fetching prices via REST')
      await useCodexStore.getState().fetchPrices()
      const count = Object.keys(useCodexStore.getState().prices).length
      console.info('[Dashboard] Prices fetched —', count, 'symbols in store')
      setPricesFetched(true)
    }

    // Immediate fetch on mount — don't wait for WS
    fetchState()
    fetchPricesOnce()

    if (wsConnected) {
      console.info('[Dashboard] WS connected — REST polling stopped')
      return
    }

    console.info('[Dashboard] WS not connected — starting 15 s REST polling fallback')
    // Keep retrying every 15 s until WS connects
    const t = setInterval(() => {
      fetchState()
      useCodexStore.getState().fetchPrices()
    }, 15_000)
    return () => clearInterval(t)
  }, [wsConnected])

  // Fetch learning data (proposals, IC weights, grades) on mount, every 30s,
  // and whenever WS reconnects so historical learnings are always visible.
  useEffect(() => {
    const { addProposal } = useCodexStore.getState()
    const fetchLearning = async () => {
      console.info('[Dashboard] Fetching learning data (proposals, IC weights, grades)')
      try {
        const [proposalsRes, icRes, gradesRes] = await Promise.all([
          fetch(api(API_ENDPOINTS.LEARNING_PROPOSALS)),
          fetch(api(API_ENDPOINTS.LEARNING_IC_WEIGHTS)),
          fetch(api(API_ENDPOINTS.LEARNING_GRADES)),
        ])
        if (proposalsRes.ok) {
          const data = await proposalsRes.json()
          const existing = useCodexStore.getState().proposals
          const existingIds = new Set(existing.map((p) => p.id))
          const newOnes = (data.proposals ?? []).filter((p: Record<string, unknown>) => !existingIds.has(p.id as string))
          console.info('[Dashboard] Proposals — total:', data.proposals?.length ?? 0, 'new:', newOnes.length)
          for (const p of newOnes) {
            addProposal({ proposal_type: (p.proposal_type as ProposalType) ?? 'parameter_change', content: JSON.stringify(p.content), requires_approval: p.requires_approval !== false, confidence: p.confidence as number | undefined, reflection_trace_id: p.reflection_trace_id as string | undefined, timestamp: (p.timestamp as string) ?? new Date().toISOString() })
          }
        } else {
          console.warn('[Dashboard] /learning/proposals responded', proposalsRes.status)
        }
        if (icRes.ok) {
          const data = await icRes.json()
          const weights = data.current_weights ?? {}
          console.info('[Dashboard] IC weights —', Object.keys(weights).length, 'factors')
          setIcWeights(weights)
        } else {
          console.warn('[Dashboard] /learning/ic-weights responded', icRes.status)
        }
        if (gradesRes.ok) {
          const data = await gradesRes.json()
          const grades = (data.grades ?? []).slice(0, 10)
          console.info('[Dashboard] Grades —', grades.length, 'entries')
          setGradeHistory(grades)
        } else {
          console.warn('[Dashboard] /learning/grades responded', gradesRes.status)
        }
      } catch (err) {
        console.warn('[Dashboard] fetchLearning failed:', err)
      }
    }
    fetchLearning()
    const interval = setInterval(fetchLearning, 30_000)
    return () => clearInterval(interval)
  }, [wsConnected]) // re-run on reconnect so we catch data that arrived while away

  // Fetch trade feed on mount and every 30s
  useEffect(() => {
    const fetchTradeFeed = async () => {
      try {
        const r = await fetch(api(API_ENDPOINTS.DASHBOARD_TRADE_FEED))
        if (r.ok) {
          const d = await r.json()
          const trades = d.trades ?? []
          console.info('[Dashboard] Trade feed —', trades.length, 'trades')
          useCodexStore.getState().setTradeFeed(trades)
        } else {
          console.warn('[Dashboard] /dashboard/trade-feed responded', r.status)
        }
      } catch (err) {
        console.warn('[Dashboard] fetchTradeFeed failed:', err)
      }
    }
    fetchTradeFeed()
    const interval = setInterval(fetchTradeFeed, 30_000)
    return () => clearInterval(interval)
  }, [])

  // Fetch performance summary on mount, every 30 s, and on WS reconnect.
  // Without the interval, a single transient fetch failure on initial mount
  // left performanceSummary permanently null, so the PnL headline card
  // stayed at "--" even after fills successfully landed in the DB. Matches
  // the retry cadence of fetchTradeFeed / fetchLearning.
  useEffect(() => {
    const fetchPerformance = async () => {
      try {
        const r = await fetch(api(API_ENDPOINTS.DASHBOARD_PERFORMANCE_TRENDS))
        const d = await r.json()
        if (d.summary) useCodexStore.getState().setPerformanceSummary(d.summary)
      } catch {
        // non-fatal
      }
    }
    fetchPerformance()
    const interval = setInterval(fetchPerformance, 30_000)
    return () => clearInterval(interval)
  }, [wsConnected])

  // Fetch agent instances on mount and every 30s
  useEffect(() => {
    const fetchAgentInstances = async () => {
      try {
        const r = await fetch(api(API_ENDPOINTS.DASHBOARD_AGENT_INSTANCES))
        const d = await r.json()
        useCodexStore.getState().setAgentInstances(d.instances ?? [])
        setApiHealth((prev) => ({ ...prev, agentInstances: r.ok ? 'ok' : 'error' }))
      } catch {
        // non-fatal
        setApiHealth((prev) => ({ ...prev, agentInstances: 'error' }))
      }
    }
    fetchAgentInstances()
    const interval = setInterval(fetchAgentInstances, 30_000)
    return () => clearInterval(interval)
  }, [])

  // Fetch persisted history view so operators can confirm durable writes.
  useEffect(() => {
    const fetchPersistedHistory = async () => {
      try {
        const r = await fetch(api(API_ENDPOINTS.EVENTS_HISTORY))
        if (!r.ok) {
          setApiHealth((prev) => ({ ...prev, eventHistory: 'error' }))
          return
        }
        const d = await r.json()
        setPersistedCounts((d.stream_counts ?? []) as PersistedStreamCount[])
        setPersistedEvents((d.persisted_events ?? []) as PersistedHistoryItem[])
        setPersistedLogs((d.persisted_logs ?? []) as PersistedHistoryItem[])
        setApiHealth((prev) => ({ ...prev, eventHistory: 'ok' }))
      } catch {
        // non-fatal
        setApiHealth((prev) => ({ ...prev, eventHistory: 'error' }))
      }
    }
    fetchPersistedHistory()
    const interval = setInterval(fetchPersistedHistory, 30_000)
    return () => clearInterval(interval)
  }, [])

  const formatTimeAgoSafe = useCallback((date: Date) => formatTimeAgo(date), [])
  const summary = useMemo(() => {
    const dailyPnlNumeric = orders.reduce((sum, order) => sum + (toFiniteNumber(order?.pnl) ?? 0), 0)
    const closedTrades = orders.filter((order) => isClosedTrade(order) && toFiniteNumber(order?.pnl) != null)
    const wins = closedTrades.filter((order) => (toFiniteNumber(order?.pnl) ?? 0) > 0).length
    const winRate = closedTrades.length > 0 ? (wins / closedTrades.length) * 100 : null
    const activePositions = positions.filter((position) => position?.side === 'long' || position?.side === 'short').length
    const dailyChangeFromMetric = getMetric(systemMetrics, 'daily_change_pct')
    const dailyChangeFromDashboard = toFiniteNumber((dashboardData as Record<string, unknown> | null)?.['daily_change_pct'])
    const baseEquity = getMetric(systemMetrics, 'portfolio_value')
      ?? getMetric(systemMetrics, 'account_equity')
      ?? getMetric(systemMetrics, 'equity')
      ?? getMetric(systemMetrics, 'starting_equity')
    const computedDailyChange = baseEquity && baseEquity > 0 ? (dailyPnlNumeric / baseEquity) * 100 : null
    const dailyChange = dailyChangeFromMetric ?? dailyChangeFromDashboard ?? computedDailyChange

    return {
      dailyPnlNumeric,
      winRate,
      activePositions,
      dailyChange,
      hasOrders: orders.length > 0,
      hasClosedTrades: closedTrades.length > 0,
    }
  }, [orders, positions, systemMetrics, dashboardData])

  const fallbackPerformanceSummary = useMemo(() => {
    const closedPnls = orders
      .filter((order) => isClosedTrade(order))
      .map((order) => toFiniteNumber(order?.pnl))
      .filter((pnl): pnl is number => pnl != null)
    if (closedPnls.length === 0) return null
    const total = closedPnls.reduce((sum, pnl) => sum + pnl, 0)
    const wins = closedPnls.filter((pnl) => pnl > 0)
    return {
      total_pnl: total,
      win_rate: wins.length / closedPnls.length,
      best_trade: Math.max(...closedPnls),
      worst_trade: Math.min(...closedPnls),
    }
  }, [orders])

  const resolvedPerformanceSummary = performanceSummary ?? fallbackPerformanceSummary

  const realAgents = useMemo(() => {
    const grouped = agentLogs.reduce<Record<string, { displayName: string; count: number; lastSeen: Date | null }>>((acc, log) => {
      const name = sanitizeValue(log?.agent_name || log?.agent)
      if (name === '--') return acc
      const agentKey = canonicalAgentKey(name)
      const safeDate = parseTimestamp(log?.timestamp || log?.created_at)
      const existing = acc[agentKey] ?? { displayName: name, count: 0, lastSeen: null }
      const newest = !existing.lastSeen || (safeDate && safeDate > existing.lastSeen) ? safeDate : existing.lastSeen
      acc[agentKey] = { displayName: existing.displayName, count: existing.count + 1, lastSeen: newest }
      return acc
    }, {})

    const now = Date.now()
    const incomingAgents = Object.entries(grouped).map<AgentSummary>(([, data]) => {
      const ageMs = data.lastSeen ? now - data.lastSeen.getTime() : Infinity
      const status: AgentSummary['status'] = ageMs <= AGENT_LIVE_THRESHOLD_MS ? 'Live' : ageMs <= AGENT_STALE_THRESHOLD_MS ? 'Stale' : 'Idle'
      const tier: AgentSummary['tier'] = status === 'Live' ? 'active' : data.count > 0 ? 'challenger' : 'inactive'
      return {
        name: data.displayName,
        realtimeCount: data.count,
        persistedCount: 0,
        lastSeen: data.lastSeen,
        status,
        tier,
        source: 'realtime',
      }
    })

    const normalizedByName = new Map(incomingAgents.map((agent) => [canonicalAgentKey(agent.name), agent]))
    for (const status of agentStatuses) {
      const agentKey = canonicalAgentKey(status.name)
      const existing = normalizedByName.get(agentKey)
      const statusDate = parseHeartbeatTimestamp(status)
      const ageMs = statusDate ? now - statusDate.getTime() : Number.POSITIVE_INFINITY
      const eventCount = status.event_count ?? 0
      const mappedStatus: AgentSummary['status'] = ageMs <= AGENT_LIVE_THRESHOLD_MS ? 'Live' : eventCount === 0 ? 'Idle' : 'Stale'
      const mergedStatus = pickHigherPriorityStatus(existing?.status, mappedStatus)
      const lastSeen = [existing?.lastSeen, statusDate]
        .filter((d): d is Date => d instanceof Date)
        .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
      normalizedByName.set(agentKey, {
        name: existing?.name ?? status.name,
        realtimeCount: Math.max(existing?.realtimeCount ?? 0, status.event_count ?? 0),
        persistedCount: existing?.persistedCount ?? 0,
        lastSeen,
        status: mergedStatus,
        tier: mergedStatus === 'Live' ? 'active' : mergedStatus === 'Error' ? 'inactive' : 'challenger',
        source: existing ? 'hybrid' : 'realtime',
      })
    }

    for (const inst of agentInstances) {
      const agentKey = canonicalAgentKey(inst.pool_name)
      const existing = normalizedByName.get(agentKey)
      const startedDate = parseTimestamp(inst.started_at)
      const mappedStatus: AgentSummary['status'] = inst.status === 'active' ? 'Stale' : 'Idle'
      const mergedStatus = pickHigherPriorityStatus(existing?.status, mappedStatus)
      const lastSeen = [existing?.lastSeen, startedDate]
        .filter((d): d is Date => d instanceof Date)
        .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
      normalizedByName.set(agentKey, {
        name: existing?.name ?? inst.pool_name,
        realtimeCount: existing?.realtimeCount ?? 0,
        persistedCount: Math.max(existing?.persistedCount ?? 0, inst.event_count ?? 0),
        lastSeen,
        status: mergedStatus,
        tier: mergedStatus === 'Live' ? 'active' : mergedStatus === 'Error' ? 'inactive' : 'challenger',
        source: existing ? 'hybrid' : 'persisted',
      })
    }

    const priority: Record<AgentSummary['status'], number> = {
      Live: 0,
      Stale: 1,
      Error: 2,
      Idle: 3,
    }

    return Array.from(normalizedByName.values()).sort((a, b) => {
      const byStatus = priority[a.status] - priority[b.status]
      if (byStatus !== 0) return byStatus
      return a.name.localeCompare(b.name)
    })
  }, [agentLogs, agentStatuses, agentInstances])

  useEffect(() => {
    if (!wsConnected || realAgents.length > 0) {
      setShowNoAgentDataMessage(false)
      return
    }
    const timer = setTimeout(() => {
      const state = useCodexStore.getState()
      const hasAgentData = state.agentLogs.length > 0 || state.agentStatuses.length > 0 || state.agentInstances.length > 0
      if (!hasAgentData && state.wsConnected) {
        setShowNoAgentDataMessage(true)
      }
    }, 10000)
    return () => clearTimeout(timer)
  }, [realAgents.length, wsConnected])

  const learningSummary = useMemo(() => {
    const streamReflections = streamStats['reflection_outputs']?.count ?? 0
    const streamEvaluations = streamStats['agent_grades']?.count ?? 0
    const streamIcUpdates = streamStats['factor_ic_history']?.count ?? 0
    const tradesEvaluated = Math.max(
      learningEvents.filter((event) => event?.type === 'trade_evaluated').length,
      streamEvaluations,
      gradeHistory.length,
    )
    const reflectionsCompleted = Math.max(
      learningEvents.filter((event) => event?.type === 'reflection').length,
      streamReflections,
    )
    const icValuesUpdated = Math.max(
      learningEvents.filter((event) => event?.type === 'ic_update').length,
      streamIcUpdates,
      Object.keys(icWeights).length > 0 ? 1 : 0,
    )
    const strategiesTested = Math.max(
      learningEvents.filter((event) => event?.type === 'strategy_tested').length,
      proposals.length,
    )

    const dailyPnlMap = orders.reduce<Record<string, number>>((acc, order) => {
      const timestamp = new Date(String(order?.timestamp || ''))
      if (Number.isNaN(timestamp.getTime())) return acc
      const key = timestamp.toDateString()
      acc[key] = (acc[key] ?? 0) + (toFiniteNumber(order?.pnl) ?? 0)
      return acc
    }, {})

    const dayEntries = Object.entries(dailyPnlMap)
    const bestDay = dayEntries.length > 0 ? dayEntries.reduce((best, current) => (current[1] > best[1] ? current : best)) : null
    const worstDay = dayEntries.length > 0 ? dayEntries.reduce((worst, current) => (current[1] < worst[1] ? current : worst)) : null

    return {
      tradesEvaluated,
      reflectionsCompleted,
      icValuesUpdated,
      strategiesTested,
      bestDay,
      worstDay,
    }
  }, [gradeHistory.length, icWeights, learningEvents, orders, proposals.length, streamStats])

  const cleanGradeHistory = useMemo(() => {
    const seen = new Set<string>()
    return gradeHistory
      .filter((g) => {
        const hasGrade = typeof g.grade === 'string' && g.grade.trim() !== '' && g.grade !== '--'
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
  }, [gradeHistory])

  const learningPipelineStages = useMemo(() => {
    const latestTradeTs = tradeFeed
      .map((t) => parseTimestamp(t.filled_at ?? t.created_at))
      .filter((ts): ts is Date => ts instanceof Date)
      .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
    const latestGradeTs = cleanGradeHistory
      .map((g) => parseTimestamp(g.timestamp))
      .filter((ts): ts is Date => ts instanceof Date)
      .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
    const reflectionTs = parseTimestamp(streamStats['reflection_outputs']?.lastMessageTimestamp)
    const proposalTs = proposals
      .map((p) => parseTimestamp(p.timestamp))
      .filter((ts): ts is Date => ts instanceof Date)
      .sort((a, b) => b.getTime() - a.getTime())[0] ?? null
    const icTs = parseTimestamp(streamStats['factor_ic_history']?.lastMessageTimestamp)
    const now = Date.now()
    const asStatus = (count: number, ts: Date | null, requiresInput?: number): 'Active' | 'Idle' | 'Error' => {
      if (count <= 0 && (requiresInput ?? 0) <= 0) return 'Idle'
      if (count <= 0 && (requiresInput ?? 0) > 0) return 'Error'
      if (!ts) return 'Idle'
      return now - ts.getTime() <= 10 * 60 * 1000 ? 'Active' : 'Idle'
    }

    return [
      { key: 'ingestion', label: 'Trade Ingestion', count: tradeFeed.length, lastRun: latestTradeTs, status: asStatus(tradeFeed.length, latestTradeTs) },
      { key: 'grading', label: 'Evaluation & Grading', count: cleanGradeHistory.length, lastRun: latestGradeTs, status: asStatus(cleanGradeHistory.length, latestGradeTs, tradeFeed.length) },
      { key: 'reflection', label: 'Reflection', count: learningSummary.reflectionsCompleted, lastRun: reflectionTs, status: asStatus(learningSummary.reflectionsCompleted, reflectionTs, cleanGradeHistory.length) },
      { key: 'proposals', label: 'Strategy Proposals', count: proposals.length, lastRun: proposalTs, status: asStatus(proposals.length, proposalTs, learningSummary.reflectionsCompleted) },
      { key: 'ic', label: 'IC Updates', count: learningSummary.icValuesUpdated, lastRun: icTs, status: asStatus(learningSummary.icValuesUpdated, icTs, learningSummary.reflectionsCompleted) },
    ] as const
  }, [cleanGradeHistory, learningSummary.icValuesUpdated, learningSummary.reflectionsCompleted, proposals, streamStats, tradeFeed])

  const wiringFreshness = useMemo(() => {
    const now = Date.now()
    const latestHeartbeat = agentStatuses
      .map((row) => parseHeartbeatTimestamp(row)?.getTime() ?? Number.NaN)
      .filter((ts) => Number.isFinite(ts))
      .sort((a, b) => b - a)[0]
    const latestInstance = agentInstances
      .map((row) => new Date(String(row.started_at || '')).getTime())
      .filter((ts) => Number.isFinite(ts))
      .sort((a, b) => b - a)[0]
    const latestLog = agentLogs
      .map((row) => new Date(String(row.timestamp || row.created_at || '')).getTime())
      .filter((ts) => Number.isFinite(ts))
      .sort((a, b) => b - a)[0]

    return {
      heartbeatAgeMs: latestHeartbeat ? now - latestHeartbeat : null,
      instanceAgeMs: latestInstance ? now - latestInstance : null,
      logAgeMs: latestLog ? now - latestLog : null,
    }
  }, [agentStatuses, agentInstances, agentLogs])

  const tickerEntries = useMemo(
    () => TICKER_SYMBOLS.map((symbol) => [symbol, prices[symbol]] as const),
    [prices]
  )

  const hasSyncDrift = useMemo(() => {
    const hasRealtimeSignals = agentLogs.length > 0 || agentStatuses.length > 0
    return wsConnected && hasRealtimeSignals && agentInstances.length === 0
  }, [agentInstances.length, agentLogs.length, agentStatuses.length, wsConnected])

  const resolvePositionTraceId = useCallback((position: Record<string, unknown>): string | null => {
    const candidates = [
      position.trace_id,
      position.execution_trace_id,
      position.signal_trace_id,
      position.order_id,
    ]
    for (const candidate of candidates) {
      if (typeof candidate === 'string' && candidate.trim()) return candidate
    }
    return null
  }, [])

  const contentBySection = (
    <>
      {section === 'overview' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              { title: 'Daily P&L', value: summary.hasOrders ? `${summary.dailyPnlNumeric >= 0 ? '+' : '-'}${formatUSD(summary.dailyPnlNumeric)}` : '--', trend: summary.hasOrders ? (summary.dailyPnlNumeric > 0 ? 1 : summary.dailyPnlNumeric < 0 ? -1 : 0) : 0 },
              { title: 'Win Rate', value: summary.winRate == null ? '--' : `${sanitizeValue(summary.winRate.toFixed(2))}%${summary.hasClosedTrades ? '' : ' (open only)'}`, trend: 0 },
              { title: 'Active Positions', value: sanitizeValue(summary.activePositions), trend: 0 },
              { title: 'Daily Change %', value: `${sanitizeValue((summary.dailyChange ?? 0).toFixed(2))}%`, trend: (summary.dailyChange ?? 0) > 0 ? 1 : (summary.dailyChange ?? 0) < 0 ? -1 : 0 },
            ].map((item) => (
              <div key={item.title} className={cardClass}>
                <div className="mb-3 flex items-center justify-between">
                  <p className={sectionTitleClass}>{item.title}</p>
                  {item.trend > 0 ? <TrendingUp className="h-4 w-4 text-emerald-500" /> : item.trend < 0 ? <TrendingDown className="h-4 w-4 text-rose-500" /> : <span className="h-4 w-4" />}
                </div>
                <p className={valueClass}>{item.value}</p>
              </div>
            ))}
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Performance</p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                {
                  label: 'Total P&L',
                  value: resolvedPerformanceSummary != null
                    ? `${resolvedPerformanceSummary.total_pnl >= 0 ? '+' : '-'}${formatUSD(resolvedPerformanceSummary.total_pnl)}`
                    : '--',
                  colorClass: resolvedPerformanceSummary != null
                    ? resolvedPerformanceSummary.total_pnl >= 0 ? 'text-emerald-500' : 'text-rose-500'
                    : 'text-slate-900 dark:text-slate-100',
                },
                {
                  label: 'Win Rate',
                  value: resolvedPerformanceSummary != null ? `${(resolvedPerformanceSummary.win_rate * 100).toFixed(1)}%` : '--',
                  colorClass: 'text-slate-900 dark:text-slate-100',
                },
                {
                  label: 'Best Trade',
                  value: resolvedPerformanceSummary != null ? `+${formatUSD(resolvedPerformanceSummary.best_trade)}` : '--',
                  colorClass: 'text-emerald-500',
                },
                {
                  label: 'Worst Trade',
                  value: resolvedPerformanceSummary != null ? `-${formatUSD(resolvedPerformanceSummary.worst_trade)}` : '--',
                  colorClass: 'text-rose-500',
                },
              ].map((cell) => (
                <div key={cell.label} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                  <p className={mutedClass}>{cell.label}</p>
                  <p className={cn('mt-1 text-sm font-mono tabular-nums font-semibold', cell.colorClass)}>{cell.value}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:gap-4">
            <div className={cn(cardClass, 'sm:col-span-2 lg:col-span-2')}>
              <div className="mb-3 flex items-center justify-between">
                <p className={sectionTitleClass}>Equity Curve</p>
              </div>
              <EquityCurve orders={orders} />
            </div>
            <div className={cn(cardClass, 'sm:col-span-2 lg:col-span-2')}>
              <div className="mb-3 flex items-center justify-between">
                <p className={sectionTitleClass}>Agent Matrix</p>
                <p className={mutedClass}>{sanitizeValue(realAgents.length)}</p>
              </div>
              {realAgents.length === 0 ? (
                <EmptyState message="No active agents" />
              ) : (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {realAgents.map((agent) => (
                    <div
                      key={agent.name}
                      className="rounded-lg border border-slate-200 p-3 transition-transform duration-150 hover:scale-[1.02] dark:border-slate-800"
                    >
                      <div className="flex items-center justify-between">
                        <p className="text-sm font-sans font-semibold text-slate-900 dark:text-slate-100">{displayAgentName(agent.name)}</p>
                        <div className="flex items-center gap-2">
                          <span className={cn('h-1.5 w-1.5 rounded-full', 
                            agent.status === 'Live' ? 'bg-emerald-300' : 
                            agent.status === 'Stale' ? 'bg-amber-300' :
                            agent.status === 'Error' ? 'bg-rose-300' : 'bg-slate-400'
                          )} />
                          <span className={cn('text-xs font-sans font-medium',
                            agent.status === 'Live' ? 'text-emerald-300' : 
                            agent.status === 'Stale' ? 'text-amber-300' :
                            agent.status === 'Error' ? 'text-rose-300' : 'text-slate-400'
                          )}>{agent.status}</span>
                        </div>
                      </div>
                      <div className="mt-2 flex items-center justify-between">
                        <p className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">
                          {agent.realtimeCount + agent.persistedCount} events
                        </p>
                        <p className={mutedClass}>
                          {agent.lastSeen ? formatTimeAgoSafe(agent.lastSeen) : 'Never'}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className={cardClass}>
            <div className="mb-3 flex items-center justify-between">
              <p className={sectionTitleClass}>Live Market Prices</p>
              <div className="flex items-center gap-2">
                {pricesLoading ? (
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-2 animate-pulse rounded-full bg-amber-500" />
                    <span className="text-xs font-sans text-amber-500">Loading</span>
                  </div>
                ) : Object.keys(prices).length > 0 ? (
                  <div className="flex items-center gap-2">
                    <div className={cn('h-2 w-2 rounded-full', dataLatencyMs != null && dataLatencyMs <= 5_000 ? 'bg-emerald-500' : 'bg-amber-500')} />
                    <span className={cn('text-xs font-sans', dataLatencyMs != null && dataLatencyMs <= 5_000 ? 'text-emerald-500' : 'text-amber-500')}>
                      {dataLatencyMs != null && dataLatencyMs <= 5_000 ? 'Live' : 'Stale'}
                    </span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-2 rounded-full bg-slate-500" />
                    <span className="text-xs font-sans text-slate-500">No Data</span>
                  </div>
                )}
              </div>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {pricesLoading ? (
                // Show loading skeletons
                Array.from({ length: 6 }).map((_, index) => <PriceCardSkeleton key={`skeleton-${index}`} />)
              ) : (
                tickerEntries.map(([symbol, priceData]) => {
                  const price = toFiniteNumber(priceData?.price)
                  const previous = toFiniteNumber(priceData?.previousPrice)
                  const observedChange = toFiniteNumber(priceData?.change)
                  const change = observedChange ?? (price != null && previous != null ? price - previous : null)
                  const isPositive = (change ?? 0) >= 0
                  const hasData = price != null && !isNaN(price)
                  
                  return (
                    <div key={symbol} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                      <div className="flex items-center justify-between">
                        <p className={sectionTitleClass}>{sanitizeValue(symbol)}</p>
                        <div className={cn('h-2 w-2 rounded-full', hasData ? 'bg-emerald-500' : 'bg-slate-500')} />
                      </div>
                      <p className="mt-1 text-lg font-mono tabular-nums text-slate-900 dark:text-slate-100">
                        {hasData ? formatUSD(price) : '--'}
                      </p>
                      <div className="mt-2 flex items-center justify-between">
                        <p className={cn('text-xs font-mono tabular-nums', 
                          change == null || !hasData ? 'text-slate-500' : isPositive ? 'text-emerald-500' : 'text-rose-500'
                        )}>
                          {change == null || !hasData ? '--' : `${isPositive ? '▲' : '▼'} ${formatUSD(Math.abs(change))}`}
                        </p>
                        <p className={mutedClass}>{formatTimestamp((priceData?.updatedAt as string | null) ?? null)}</p>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      )}

      {section === 'trading' && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
          <div className="space-y-4 xl:col-span-3">
            <div className={cardClass}>
              <div className="mb-3 flex items-center justify-between">
                <p className={sectionTitleClass}>System Stats</p>
                <span className={mutedClass}>Live</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
                  <p className={mutedClass}>Trades</p>
                  <p className="text-sm font-mono tabular-nums text-slate-100">{tradeFeed.length}</p>
                </div>
                <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
                  <p className={mutedClass}>Positions</p>
                  <p className="text-sm font-mono tabular-nums text-slate-100">{positions.length}</p>
                </div>
                <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
                  <p className={mutedClass}>Agents</p>
                  <p className="text-sm font-mono tabular-nums text-slate-100">{realAgents.length}</p>
                </div>
                <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
                  <p className={mutedClass}>WS</p>
                  <p className={cn('text-sm font-mono tabular-nums', wsConnected ? 'text-emerald-400' : 'text-amber-400')}>
                    {wsConnected ? 'Connected' : 'Reconnecting'}
                  </p>
                </div>
              </div>
            </div>

            <div className={cardClass}>
              <div className="mb-3 flex items-center justify-between">
                <p className={sectionTitleClass}>Trade Feed</p>
                <p className={mutedClass}>{tradeFeed.length} fills</p>
              </div>
              {tradeFeed.length === 0 ? (
                <div className="rounded-lg border border-dashed border-slate-700 px-4 py-8 text-center text-xs font-sans text-slate-500">
                  Awaiting fills...
                </div>
              ) : (
                <div className="max-h-96 overflow-y-auto space-y-1">
                  {tradeFeed.slice(0, 20).map((trade) => {
                    const isBuy = trade.side === 'buy'
                    const pnl = toFiniteNumber(trade.pnl)
                    const pnlPct = toFiniteNumber(trade.pnl_percent)
                    const isPnlPositive = (pnl ?? 0) >= 0
                    const exitPrice = toFiniteNumber(trade.exit_price)
                    const qty = toFiniteNumber(trade.qty)

                    return (
                      <div key={trade.id} className="flex items-center justify-between gap-2 border-t border-slate-200 py-2 first:border-t-0 dark:border-slate-800">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className={cn('rounded px-1.5 py-0.5 text-xs font-bold', isBuy ? 'bg-emerald-500/15 text-emerald-400' : 'bg-rose-500/15 text-rose-400')}>
                            {isBuy ? 'BUY' : 'SELL'}
                          </span>
                          <span className="text-sm font-mono font-semibold text-slate-100">{trade.symbol}</span>
                          <span className={mutedClass}>
                            {qty != null ? qty : '--'} @ {exitPrice != null ? formatUSD(exitPrice) : '--'}
                          </span>
                        </div>
                        <span className={cn('text-xs font-mono tabular-nums font-semibold', isPnlPositive ? 'text-emerald-400' : 'text-rose-400')}>
                          {pnl == null ? '--' : `${isPnlPositive ? '+' : '-'}${formatUSD(pnl)}${pnlPct != null ? ` (${isPnlPositive ? '+' : ''}${pnlPct.toFixed(1)}%)` : ''}`}
                        </span>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>

          <div className="space-y-4 xl:col-span-5">
            {hasSyncDrift && (
              <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-300">
                Sync drift warning: realtime events are present, but lifecycle rows are 0.
              </div>
            )}
            <AgentStream logs={agentLogs as Array<Record<string, unknown>>} formatMessage={formatAgentMessage} />
          </div>

          <div className="space-y-4 xl:col-span-4">
            <div className={cardClass}>
              <p className={sectionTitleClass}>Portfolio Summary</p>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
                  <p className={mutedClass}>Open Positions</p>
                  <p className="text-sm font-mono tabular-nums text-slate-100">{positions.length}</p>
                </div>
                <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
                  <p className={mutedClass}>Unrealized P&amp;L</p>
                  <p className="text-sm font-mono tabular-nums text-slate-100">
                    {formatUSD(positions.reduce((sum, position) => sum + (toFiniteNumber(position?.pnl) ?? 0), 0))}
                  </p>
                </div>
              </div>
            </div>
            <PositionsTable
              positions={positions as Array<Record<string, unknown>>}
              onClose={(position) => {
                const traceId = resolvePositionTraceId(position)
                if (traceId) setActiveTraceId(traceId)
              }}
              onViewDetails={(position) => {
                const traceId = resolvePositionTraceId(position)
                if (traceId) setActiveTraceId(traceId)
              }}
            />
          </div>
        </div>
      )}

      {section === 'agents' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <div className={cardClass}>
              <p className={sectionTitleClass}>Market Ticks</p>
              <p className={valueClass}>{sanitizeValue(marketTickCount)}</p>
              <p className={mutedClass}>Last symbol: {lastMarketSymbol ?? '--'}</p>
            </div>
            <div className={cardClass}>
              <p className={sectionTitleClass}>Tracked Agents</p>
              <p className={valueClass}>{sanitizeValue(realAgents.length)}</p>
              <p className={mutedClass}>Discovered from heartbeats, instances, and logs</p>
            </div>
            <div className={cardClass}>
              <p className={sectionTitleClass}>Agent Events</p>
              <p className={valueClass}>{sanitizeValue(agentLogs.length)}</p>
              <p className={mutedClass}>Total events received</p>
            </div>
            <div className={cardClass}>
              <p className={sectionTitleClass}>Notifications</p>
              <p className={valueClass}>{sanitizeValue(notifications.length)}</p>
              <p className={mutedClass}>{notifications.filter((n) => !n.acknowledged).length} unread</p>
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-2')}>Data Wiring</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <p className={mutedClass}>
                Heartbeats (in-memory/Redis): <span className="font-mono text-slate-700 dark:text-slate-200">{agentStatuses.length}</span>
                <span className="ml-2 text-[11px]">{formatWiringAge(wiringFreshness.heartbeatAgeMs)}</span>
              </p>
              <p className={mutedClass}>
                Lifecycle rows (DB): <span className="font-mono text-slate-700 dark:text-slate-200">{agentInstances.length}</span>
                <span className="ml-2 text-[11px]">{formatWiringAge(wiringFreshness.instanceAgeMs)}</span>
              </p>
              <p className={mutedClass}>
                Agent logs (DB/WS): <span className="font-mono text-slate-700 dark:text-slate-200">{agentLogs.length}</span>
                <span className="ml-2 text-[11px]">{formatWiringAge(wiringFreshness.logAgeMs)}</span>
              </p>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {[
                { label: 'dashboard/state', value: apiHealth.dashboardState },
                { label: 'agent-instances', value: apiHealth.agentInstances },
                { label: 'history/events', value: apiHealth.eventHistory },
              ].map((apiRow) => (
                <span
                  key={apiRow.label}
                  className={cn(
                    'rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
                    apiRow.value === 'ok'
                      ? 'bg-emerald-500/10 text-emerald-500'
                      : apiRow.value === 'error'
                        ? 'bg-rose-500/10 text-rose-500'
                        : 'bg-slate-500/10 text-slate-500',
                  )}
                >
                  {apiRow.label}: {apiRow.value}
                </span>
              ))}
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Agent Status</p>
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-slate-800">
                    {['Agent', 'Status', 'Source', 'Events', 'Last Seen'].map((head) => (
                      <th key={head} className="px-2 py-2 text-left text-xs font-sans font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">{head}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {showNoAgentDataMessage ? (
                    <tr>
                      <td colSpan={5} className="px-2 py-8"><EmptyState message="No active agents" /></td>
                    </tr>
                  ) : (
                    realAgents.map((agent) => (
                      <tr key={agent.name} className="border-t border-slate-200 py-2 dark:border-slate-800">
                        <td className="px-2 py-2 text-sm font-sans text-slate-900 dark:text-slate-100">{displayAgentName(agent.name)}</td>
                        <td className="px-2 py-2 text-xs font-sans">
                          <span className="inline-flex items-center gap-2">
                            <span className={cn(
                              'h-2 w-2 rounded-full',
                              agent.status === 'Live'
                                ? 'bg-emerald-300'
                                : agent.status === 'Stale'
                                  ? 'bg-amber-300'
                                  : agent.status === 'Error'
                                    ? 'bg-rose-300'
                                    : 'bg-slate-400',
                            )} />
                            <span className="text-slate-700 dark:text-slate-300">{agent.status}</span>
                          </span>
                        </td>
                        <td className="px-2 py-2 text-xs font-sans text-slate-700 dark:text-slate-300">{formatAgentSource(agent.source)}</td>
                        <td className="px-2 py-2 text-right text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">
                          rt:{sanitizeValue(agent.realtimeCount)} · db:{sanitizeValue(agent.persistedCount)}
                        </td>
                        <td className="px-2 py-2 text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{agent.lastSeen ? formatTimeAgoSafe(agent.lastSeen) : '--'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Agent Instances</p>
            {agentInstances.length === 0 ? (
              <div className="space-y-2">
                <EmptyState message="No instances registered yet" />
                {agentStatuses.some((agent) => String(agent.status).toUpperCase() === 'ACTIVE') && (
                  <p className="text-xs font-sans text-amber-600 dark:text-amber-400">
                    Agents are reporting ACTIVE heartbeats, but no lifecycle records were returned. Check agent_instances DB writes.
                  </p>
                )}
              </div>
            ) : (
              <div className="max-h-48 overflow-y-auto">
                <table className="min-w-full">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-slate-800">
                      {['Instance Key', 'Pool', 'Status', 'Events', 'Uptime', 'Started'].map((head) => (
                        <th key={head} className="px-2 py-1.5 text-left text-xs font-sans font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">{head}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {agentInstances.map((inst) => {
                      const isActive = inst.status === 'active'
                      return (
                        <tr key={inst.id} className="border-t border-slate-200 dark:border-slate-800">
                          <td className="px-2 py-1.5 text-xs font-mono text-slate-900 dark:text-slate-100">{inst.instance_key}</td>
                          <td className="px-2 py-1.5 text-xs font-sans text-slate-600 dark:text-slate-400">{inst.pool_name}</td>
                          <td className="px-2 py-1.5 text-xs font-sans">
                            <span className="inline-flex items-center gap-1.5">
                              <span className={cn('h-2 w-2 rounded-full', isActive ? 'bg-emerald-500' : 'bg-slate-400')} />
                              <span className={isActive ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-500'}>{inst.status}</span>
                            </span>
                          </td>
                          <td className="px-2 py-1.5 text-right text-xs font-mono tabular-nums text-slate-900 dark:text-slate-100">{inst.event_count}</td>
                          <td className="px-2 py-1.5 text-xs font-mono tabular-nums text-slate-700 dark:text-slate-300">{formatUptime(inst.uptime_seconds)}</td>
                          <td className="px-2 py-1.5 text-xs font-mono text-slate-500">{formatTimestamp(inst.started_at)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <NotificationFeed notifications={notifications} wsConnected={wsConnected} onAcknowledge={acknowledgeNotification} />
        </div>
      )}

      {section === 'learning' && (
        <div className="space-y-4">
          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Learning Pipeline Status</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
              {learningPipelineStages.map((stage) => (
                <div key={stage.key} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                  <p className={mutedClass}>{stage.label}</p>
                  <p
                    className={cn(
                      'mt-1 text-xs font-semibold uppercase tracking-wide',
                      stage.status === 'Active'
                        ? 'text-emerald-500'
                        : stage.status === 'Error'
                          ? 'text-rose-500'
                          : 'text-slate-500',
                    )}
                  >
                    {stage.status}
                  </p>
                  <p className="mt-1 text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{stage.count}</p>
                  <p className="mt-1 text-[11px] font-mono text-slate-500">
                    {stage.lastRun ? `last ${formatTimeAgoSafe(stage.lastRun)}` : 'No runs yet'}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:gap-4">
            {[
              { label: 'Trades Evaluated', value: learningSummary.tradesEvaluated, Icon: FileCode, color: 'text-slate-500' },
              { label: 'Reflections Completed', value: learningSummary.reflectionsCompleted, Icon: Brain, color: 'text-slate-500' },
              { label: 'IC Values Updated', value: learningSummary.icValuesUpdated, Icon: Activity, color: 'text-slate-500' },
              { label: 'Strategies Tested', value: learningSummary.strategiesTested, Icon: Zap, color: 'text-slate-500' },
            ].map((item) => (
              <div key={item.label} className={cardClass}>
                <div className="mb-3 flex items-center justify-between">
                  <p className={sectionTitleClass}>{item.label}</p>
                  <item.Icon className={cn('h-4 w-4', item.color)} />
                </div>
                <p className={valueClass}>{sanitizeValue(item.value)}</p>
              </div>
            ))}
          </div>

          <ProposalsFeed proposals={proposals} onUpdateStatus={updateProposalStatus} />
          {proposals.length === 0 && (
            <div className="rounded-lg border border-slate-200 bg-slate-100/50 p-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900/60 dark:text-slate-300">
              No strategy proposals yet. Reflection pipeline may be idle, disconnected, or awaiting graded trades.
            </div>
          )}

          {Object.keys(icWeights).length > 0 && (
            <div className={cardClass}>
              <p className={cn(sectionTitleClass, 'mb-3')}>IC Factor Weights</p>
              <div className="space-y-2">
                {Object.entries(icWeights).map(([factor, weight]) => (
                  <div key={factor} className="flex items-center justify-between">
                    <span className="text-sm font-sans text-slate-600 dark:text-slate-400">{factor}</span>
                    <div className="flex items-center gap-2">
                      <div className="h-2 w-24 rounded-full bg-slate-200 dark:bg-slate-700">
                        <div className="h-2 rounded-full bg-slate-500" style={{ width: `${Math.round(weight * 100)}%` }} />
                      </div>
                      <span className="w-10 text-right text-xs font-mono tabular-nums text-slate-700 dark:text-slate-300">{(weight * 100).toFixed(1)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {cleanGradeHistory.length > 0 ? (
            <div className={cardClass}>
              <p className={cn(sectionTitleClass, 'mb-3')}>Grade History</p>
              <div className="overflow-x-auto">
                <table className="min-w-full">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-slate-800">
                      {['Grade', 'Score', 'Time'].map((h) => (
                        <th key={h} className="px-2 py-2 text-left text-xs font-sans font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {cleanGradeHistory.map((g, i) => (
                      <tr key={i} className="border-t border-slate-200 dark:border-slate-800">
                        <td className="px-2 py-2 text-sm font-mono font-semibold text-slate-900 dark:text-slate-100">{g.grade ?? '--'}</td>
                        <td className="px-2 py-2 text-sm font-mono tabular-nums text-slate-700 dark:text-slate-300">{g.score_pct != null ? `${g.score_pct}%` : '--'}</td>
                        <td className="px-2 py-2 text-xs font-mono text-slate-500 dark:text-slate-400">{g.timestamp ? new Date(g.timestamp).toLocaleTimeString() : '--'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <EmptyState message="No graded learning records yet" />
          )}

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Performance Summary</p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Win Rate</p>
                <p className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{summary.winRate == null ? '--' : `${sanitizeValue(summary.winRate.toFixed(2))}%`}</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Total P&L</p>
                <p className={cn('text-sm font-mono tabular-nums', summary.dailyPnlNumeric >= 0 ? 'text-emerald-500' : 'text-rose-500')}>
                  {resolvedPerformanceSummary != null
                    ? `${resolvedPerformanceSummary.total_pnl >= 0 ? '+' : '-'}${formatUSD(resolvedPerformanceSummary.total_pnl)}`
                    : '--'}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Best Day</p>
                <p className="text-sm font-mono tabular-nums text-emerald-500">
                  {learningSummary.bestDay ? `${learningSummary.bestDay[0]} (${learningSummary.bestDay[1] >= 0 ? '+' : '-'}${formatUSD(learningSummary.bestDay[1])})` : 'N/A'}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Worst Day</p>
                <p className="text-sm font-mono tabular-nums text-rose-500">
                  {learningSummary.worstDay ? `${learningSummary.worstDay[0]} (${learningSummary.worstDay[1] >= 0 ? '+' : '-'}${formatUSD(learningSummary.worstDay[1])})` : 'N/A'}
                </p>
              </div>
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-2')}>Learning Runtime Notes</p>
            <p className={mutedClass}>
              Reflection agent status:{' '}
              <span className="font-mono text-slate-700 dark:text-slate-200">
                {realAgents.find((agent) => canonicalAgentKey(agent.name) === 'REFLECTION_AGENT')?.status ?? 'Unknown'}
              </span>
            </p>
            <p className={cn(mutedClass, 'mt-1')}>
              Last grade timestamp:{' '}
              <span className="font-mono text-slate-700 dark:text-slate-200">
                {cleanGradeHistory[0]?.timestamp ? formatTimestamp(cleanGradeHistory[0].timestamp) : 'No grades yet'}
              </span>
            </p>
          </div>
        </div>
      )}

      {section === 'proposals' && <ProposalsSection />}

      {section === 'system' && (
        <div className="space-y-4">
          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>System Health</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Data latency</p>
                <p className="text-sm font-mono">{formatAgeFromMs(effectiveLatencyMs)} ({effectiveLatencyMs ?? '--'}ms)</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Events/sec throughput</p>
                <p className="text-sm font-mono">{throughput.toFixed(2)}</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Pipeline status</p>
                <p className={cn('text-sm font-semibold', pipelineStatus === 'Healthy' ? 'text-emerald-500' : pipelineStatus === 'Degraded' ? 'text-amber-500' : 'text-rose-500')}>{pipelineStatus}</p>
              </div>
            </div>
          </div>

          {pipelineWarning && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-600 dark:text-amber-400">
              Signals generated but no orders placed
            </div>
          )}
          {!hasMarketData && (
            <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-600 dark:text-rose-400">
              No market data received
            </div>
          )}
          {hasMarketData && !latestTickTs && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-600 dark:text-amber-400">
              Market events are arriving via WebSocket, but market_ticks lag metrics are missing.
            </div>
          )}
          {systemFeedError && (
            <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-600 dark:text-rose-400">
              {systemFeedError}
            </div>
          )}
          {!persistenceEnabled && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-600 dark:text-amber-400">
              Persistence appears disabled (no persisted events/logs). Agents/Learning views may show incomplete history.
            </div>
          )}

          {/* ── Connection Diagnostics ── always visible so broken configs are obvious */}
          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Connection Diagnostics</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>WebSocket</p>
                <p className={cn('mt-1 text-sm font-semibold', wsConnected ? 'text-emerald-500' : 'text-rose-500')}>
                  {wsConnected ? '● Connected' : '● Disconnected'}
                </p>
                <p className="mt-1 break-all text-[10px] font-mono text-slate-400">
                  {typeof window !== 'undefined'
                    ? (process.env.NEXT_PUBLIC_WS_URL
                        ? process.env.NEXT_PUBLIC_WS_URL.replace(/^https?:\/\//, 'wss://').replace(/\/$/, '') + '/ws/dashboard'
                        : process.env.NEXT_PUBLIC_API_URL
                          ? process.env.NEXT_PUBLIC_API_URL.replace(/\/api\/?$/, '').replace(/^https?:\/\//, 'wss://') + '/ws/dashboard'
                          : window.location.host + '/ws/dashboard (same-origin)')
                    : '—'}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>API Base</p>
                <p className="mt-1 break-all text-xs font-mono text-slate-700 dark:text-slate-300">
                  {process.env.NEXT_PUBLIC_API_URL ?? '/api (fallback)'}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Prices / REST</p>
                <p className={cn('mt-1 text-sm font-semibold', Object.keys(prices).length > 0 ? 'text-emerald-500' : pricesFetched ? 'text-amber-500' : 'text-slate-400')}>
                  {Object.keys(prices).length > 0 ? `● ${Object.keys(prices).length} symbols` : pricesFetched ? '● Fetched – poller offline?' : '● Waiting…'}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Reconnect attempts</p>
                <p className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{wsDiagnostics.reconnectAttempts}</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Message rate</p>
                <p className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{wsDiagnostics.messageRate.toFixed(2)} /sec</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Last error</p>
                <p className="text-xs font-mono text-slate-700 dark:text-slate-300">{wsDiagnostics.lastError ?? 'None'}</p>
              </div>
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>PnL Clarity</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Realized</p><p className="text-sm font-mono">{formatUSD(realizedPnl)}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Unrealized</p><p className="text-sm font-mono">{formatUSD(unrealizedPnl)}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Session</p><p className="text-sm font-mono">{formatUSD(realizedPnl + unrealizedPnl)}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Total (DB)</p><p className="text-sm font-mono">{resolvedPerformanceSummary ? formatUSD(resolvedPerformanceSummary.total_pnl) : '--'}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Trades</p><p className="text-sm font-mono">{totalTrades}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Win rate</p><p className="text-sm font-mono">{pnlWinRate.toFixed(1)}%</p></div>
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Pipeline Handoff</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Signals (stream)</p><p className="text-sm font-mono">{signalsCount}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Orders</p><p className="text-sm font-mono">{ordersCount}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Executions</p><p className="text-sm font-mono">{executionsCount}</p></div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"><p className={mutedClass}>Signal Agent (RT)</p><p className="text-sm font-mono">{signalAgentRealtimeCount}</p></div>
            </div>
            <p className={cn(mutedClass, 'mt-2')}>
              Reasoning: <span className="font-mono">{reasoningAgentStatus}</span> → Execution: <span className="font-mono">{executionAgentStatus}</span>
            </p>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Pipeline Status</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {['market_ticks', 'signals', 'orders', 'executions', 'agent_logs', 'risk_alerts', 'notifications'].map((streamName) => {
                const stat = streamStats[streamName] ?? { count: 0, lastMessageTimestamp: null }
                const isLive = Boolean(stat.lastMessageTimestamp && Date.now() - new Date(stat.lastMessageTimestamp).getTime() < 60_000)
                return (
                  <div key={streamName} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">{streamName}</p>
                      <span className={cn('h-2 w-2 rounded-full', isLive ? 'bg-emerald-500' : 'bg-slate-500')} />
                    </div>
                    <p className="mt-1 text-lg font-mono tabular-nums text-slate-900 dark:text-slate-100">{stat.count}</p>
                  </div>
                )
              })}
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>WebSocket Status</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Connection</p>
                <p className={cn('text-sm font-semibold', wsConnected ? 'text-emerald-500' : 'text-slate-500')}>{wsConnected ? 'Connected' : 'Disconnected'}</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Messages Received</p>
                <p className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{wsMessageCount}</p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={mutedClass}>Last Message</p>
                <p className="text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100">{formatTimestamp(wsLastMessageTimestamp)}</p>
              </div>
            </div>
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Recent Events</p>
            {recentEvents.length === 0 ? (
              <EmptyState message={wsConnected ? 'No websocket events yet' : 'Stream disconnected'} />
            ) : (
              <div className="space-y-2">
                {recentEvents.map((event, index) => (
                  <div key={`${event.msgId}-${index}`} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
                    <span
                      className={cn(
                        'rounded px-2 py-0.5 text-xs font-semibold',
                        event.stream === 'market_ticks'
                          ? 'bg-emerald-500/15 text-emerald-500'
                          : event.stream === 'signals'
                            ? 'bg-slate-500/10 text-slate-500'
                            : event.stream === 'orders'
                              ? 'bg-amber-500/15 text-amber-500'
                              : 'bg-slate-500/15 text-slate-400'
                      )}
                    >
                      {event.stream}
                    </span>
                    <span className="text-xs font-mono text-slate-500">{event.msgId.slice(0, 10)}</span>
                    <span className="text-xs font-mono text-slate-500">{formatTimestamp(event.timestamp)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Agent Observability</p>
            {agentStatuses.length === 0 ? (
              <EmptyState message="No agent status yet" icon={Brain} />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead><tr className="text-left text-slate-500"><th className="pb-2">Agent</th><th>Status</th><th>Signals</th><th>Last action</th></tr></thead>
                  <tbody>
                    {agentStatuses.map((agent) => (
                      <tr key={agent.name} className="border-t border-slate-200 dark:border-slate-800">
                        <td className="py-2 font-semibold">{agent.name}</td>
                        <td>{agent.status}</td>
                        <td className="font-mono">{agent.event_count}</td>
                        <td>{agent.last_event || '--'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className={cardClass}>
            <p className={cn(sectionTitleClass, 'mb-3')}>Persisted Event History</p>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={cn(mutedClass, 'mb-2')}>Processed counts by stream</p>
                {persistedCounts.length === 0 ? (
                  <p className={mutedClass}>{isInMemoryMode ? 'In-memory mode (no DB persistence)' : 'Persistence not enabled'}</p>
                ) : (
                  <div className="space-y-1">
                    {persistedCounts.slice(0, 8).map((row) => (
                      <div key={row.stream} className="flex items-center justify-between text-xs font-mono">
                        <span className="text-slate-600 dark:text-slate-300">{row.stream}</span>
                        <span className="text-slate-900 dark:text-slate-100">{row.processed_count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <p className={cn(mutedClass, 'mb-2')}>Latest persisted events</p>
                {persistedEvents.length === 0 ? (
                  <p className={mutedClass}>{isInMemoryMode ? 'In-memory mode (no DB persistence)' : 'Persistence not enabled'}</p>
                ) : (
                  <div className="space-y-1">
                    {persistedEvents.slice(0, 8).map((evt) => (
                      <div key={evt.id} className="flex items-center justify-between text-xs font-mono">
                        <span className="text-slate-600 dark:text-slate-300">{sanitizeValue(evt.kind)}</span>
                        <span className="text-slate-500">{formatTimestamp(evt.created_at)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="mt-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
              <p className={cn(mutedClass, 'mb-2')}>Latest persisted agent logs</p>
              {persistedLogs.length === 0 ? (
                <p className={mutedClass}>{isInMemoryMode ? 'In-memory mode (no DB persistence)' : 'Persistence not enabled'}</p>
              ) : (
                <div className="space-y-1">
                  {persistedLogs.slice(0, 10).map((log) => (
                    <button
                      key={log.id}
                      type="button"
                      className="flex w-full items-center justify-between rounded px-1 py-1 text-left text-xs font-mono hover:bg-slate-100 dark:hover:bg-slate-800"
                      onClick={() => log.trace_id && setActiveTraceId(log.trace_id)}
                    >
                      <span className="text-slate-600 dark:text-slate-300">{sanitizeValue(log.kind)}</span>
                      <span className="text-slate-500">{formatTimestamp(log.created_at)}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )

  return (
    <div className="min-h-screen bg-slate-50 pb-20 dark:bg-slate-950 lg:pb-4">
      <main className="mx-auto max-w-7xl space-y-4 px-4 py-5">
        <div
          className={cn(
            'rounded-lg border px-3 py-2 text-xs font-semibold uppercase tracking-widest',
            systemStatus === 'trading'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-300'
              : systemStatus === 'booting'
                ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-300'
                : systemStatus === 'error'
                  ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/30 dark:text-rose-300'
                  : 'border-slate-200 bg-slate-100 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300'
          )}
        >
          System Status: {systemStatus}
        </div>
        {contentBySection}
      </main>

      {activeTraceId && (
        <TraceModal traceId={activeTraceId} onClose={() => setActiveTraceId(null)} />
      )}
    </div>
  )
}
