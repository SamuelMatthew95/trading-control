'use client'

import { useEffect, useState } from 'react'

import { API_ENDPOINTS, apiFetch } from '@/lib/apiClient'
import { LEARNING_REFRESH_MS, gradeColor } from '@/lib/grade-colors'
import { agentDisplayName } from '@/constants/agents'

type LatestGrade = {
  trace_id: string
  grade: string | null
  score_pct: number | null
  metrics: Record<string, number>
  fills_graded: number | null
  timestamp: string | null
}

type Proposal = {
  trace_id: string
  proposal_type: string | null
  action: string | null
  applied: boolean
  applied_at: string | null
  applied_by: string | null
  message: string | null
  timestamp: string | null
}

type LossAttribution = {
  symbol: string
  signal_type: string
  trades: number
  losses: number
  total_pnl: number
  avg_pnl: number
}

type ControlPlane = {
  trading_paused: boolean
  trading_paused_reason: string | null
  signal_weight_scale: number
  suspended_agents: { agent_name: string; suspended_until: number | null }[]
}

type LearningLoopState = {
  latest_grade: LatestGrade | null
  recent_proposals: Proposal[]
  loss_attribution: LossAttribution[]
  control_plane: ControlPlane | null
  timestamp: string
}

// A shadow ChallengerAgent (GET /dashboard/challengers). Carries the REAL
// own-vs-baseline shadow evidence so the panel shows what the config actually did.
type ChallengerInfo = {
  challenger_id: string
  fills: number
  max_fills: number
  running: boolean
  strategy?: string
  shadow_trades?: number
  shadow_win_rate?: number
  shadow_pnl?: number
  beats_baseline_shadow?: boolean
}

// A pending parameter-change PR artifact (GET /learning/pending-param-changes).
type PendingParamChange = {
  parameter: string
  previous_value: number | string | null
  proposed_value: number | string | null
  reason: string
  timestamp: string | null
}


const fmtUSD = (n: number | null | undefined): string => {
  // Guard malformed API rows: a missing/non-finite pnl renders '--', never 'NaN'.
  if (n == null || !Number.isFinite(n)) return '--'
  return (n >= 0 ? '+' : '') + n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

export function LearningLoopPanel() {
  const [state, setState] = useState<LearningLoopState | null>(null)
  const [challengers, setChallengers] = useState<ChallengerInfo[]>([])
  const [pendingPRs, setPendingPRs] = useState<PendingParamChange[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const data = await apiFetch<LearningLoopState>(API_ENDPOINTS.LEARNING_LOOP)
        if (!cancelled) {
          setState(data)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'fetch_failed')
      }
      // Challenger list is best-effort — its absence must not blank the panel.
      try {
        const ch = await apiFetch<{ challengers: ChallengerInfo[] }>(
          API_ENDPOINTS.DASHBOARD_CHALLENGERS,
        )
        if (!cancelled) setChallengers(ch.challengers ?? [])
      } catch {
        // non-fatal
      }
      // Pending parameter-change PRs (GitOps loop) — also best-effort.
      try {
        const pr = await apiFetch<{ items: PendingParamChange[] }>(
          API_ENDPOINTS.LEARNING_PENDING_PARAM_CHANGES,
        )
        if (!cancelled) setPendingPRs(pr.items ?? [])
      } catch {
        // non-fatal
      }
    }
    load()
    const id = window.setInterval(load, LEARNING_REFRESH_MS)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  const cp = state?.control_plane ?? null
  const grade = state?.latest_grade ?? null
  const proposals = state?.recent_proposals ?? []
  const attribution = state?.loss_attribution ?? []
  const appliedCount = proposals.filter((p) => p.applied).length
  const pendingCount = proposals.length - appliedCount

  return (
    <div className="rounded-xl border border-slate-300 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          Learning Loop
        </p>
        {error ? (
          <span className="text-xs font-mono text-rose-500">err: {error}</span>
        ) : (
          <span className="text-xs text-slate-400">
            {state?.timestamp ? new Date(state.timestamp).toLocaleTimeString() : '--'}
          </span>
        )}
      </div>

      {/* Tile row: grade + control plane */}
      <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-4">
        <div className="rounded-lg border border-slate-300 p-3 dark:border-slate-800">
          <p className="text-xs text-slate-500 dark:text-slate-400">Latest Grade</p>
          <p className={`text-2xl font-mono font-semibold ${gradeColor(grade?.grade ?? null)}`}>
            {grade?.grade ?? '--'}
          </p>
          <p className="text-xs font-mono text-slate-500">
            {grade?.score_pct != null ? `${grade.score_pct.toFixed(1)}%` : '--'}
          </p>
        </div>
        <div className="rounded-lg border border-slate-300 p-3 dark:border-slate-800">
          <p className="text-xs text-slate-500 dark:text-slate-400">Trading Paused</p>
          <p
            className={`text-lg font-mono font-bold ${cp?.trading_paused ? 'text-rose-500' : 'text-emerald-500'}`}
          >
            {cp?.trading_paused ? 'PAUSED' : 'LIVE'}
          </p>
          {cp?.trading_paused && cp.trading_paused_reason ? (
            <p className="text-xs text-slate-500 truncate" title={cp.trading_paused_reason}>
              {cp.trading_paused_reason}
            </p>
          ) : null}
        </div>
        <div className="rounded-lg border border-slate-300 p-3 dark:border-slate-800">
          <p className="text-xs text-slate-500 dark:text-slate-400">Signal Weight</p>
          <p className="text-lg font-mono font-bold tabular-nums">
            {cp ? cp.signal_weight_scale.toFixed(3) : '--'}
          </p>
          <p className="text-xs text-slate-500">
            {cp && cp.signal_weight_scale < 1 ? 'dampened' : 'full'}
          </p>
        </div>
        <div className="rounded-lg border border-slate-300 p-3 dark:border-slate-800">
          <p className="text-xs text-slate-500 dark:text-slate-400">Proposals</p>
          <p className="text-lg font-mono font-bold tabular-nums">
            <span className="text-emerald-500">{appliedCount}</span>
            <span className="text-slate-400"> / </span>
            <span className="text-amber-500">{pendingCount}</span>
          </p>
          <p className="text-xs text-slate-500">applied / pending</p>
        </div>
      </div>

      {/* Suspended agents (control-plane effect) — only when any are suspended */}
      {cp && cp.suspended_agents.length > 0 && (
        <div className="mb-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Suspended Agents
          </p>
          <div className="flex flex-wrap gap-2">
            {cp.suspended_agents.map((s) => (
              <span
                key={s.agent_name}
                className="rounded-full border border-rose-300 bg-rose-50 px-2 py-0.5 text-xs font-mono text-rose-600 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-400"
              >
                {agentDisplayName(s.agent_name)}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Proposals list */}
      <div className="mb-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Recent Proposals
        </p>
        {proposals.length === 0 ? (
          <p className="text-xs text-slate-500">No proposals yet.</p>
        ) : (
          <div className="max-h-48 overflow-y-auto rounded-lg border border-slate-300 dark:border-slate-800">
            <table className="w-full text-xs font-mono">
              <thead className="bg-slate-100 dark:bg-slate-800/50">
                <tr className="text-left">
                  <th className="p-2">Type</th>
                  <th className="p-2">Action</th>
                  <th className="p-2">State</th>
                  <th className="p-2">When</th>
                </tr>
              </thead>
              <tbody>
                {proposals.slice(0, 10).map((p) => (
                  <tr key={p.trace_id} className="border-t border-slate-200 dark:border-slate-800">
                    <td className="p-2">{p.proposal_type ?? '--'}</td>
                    <td className="p-2 text-slate-500">{p.action ?? p.message ?? '--'}</td>
                    <td className="p-2">
                      {p.applied ? (
                        <span className="text-emerald-500">applied</span>
                      ) : (
                        <span className="text-amber-500">pending</span>
                      )}
                    </td>
                    <td className="p-2 text-slate-500">
                      {p.timestamp ? new Date(p.timestamp).toLocaleTimeString() : '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Loss attribution */}
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Loss Attribution
        </p>
        {attribution.length === 0 ? (
          <p className="text-xs text-slate-500">
            No closed trades yet — attribution appears once positions close.
          </p>
        ) : (
          <div className="max-h-48 overflow-y-auto rounded-lg border border-slate-300 dark:border-slate-800">
            <table className="w-full text-xs font-mono">
              <thead className="bg-slate-100 dark:bg-slate-800/50">
                <tr className="text-left">
                  <th className="p-2">Symbol</th>
                  <th className="p-2">Signal</th>
                  <th className="p-2 text-right">Trades</th>
                  <th className="p-2 text-right">Losses</th>
                  <th className="p-2 text-right">Total PnL</th>
                  <th className="p-2 text-right">Avg PnL</th>
                </tr>
              </thead>
              <tbody>
                {attribution.slice(0, 12).map((row) => {
                  const negative = row.total_pnl < 0
                  return (
                    <tr
                      key={`${row.symbol}-${row.signal_type}`}
                      className="border-t border-slate-200 dark:border-slate-800"
                    >
                      <td className="p-2">{row.symbol}</td>
                      <td className="p-2 text-slate-500">{row.signal_type}</td>
                      <td className="p-2 text-right">{row.trades}</td>
                      <td className="p-2 text-right">{row.losses}</td>
                      <td
                        className={`p-2 text-right ${negative ? 'text-rose-500' : 'text-emerald-500'}`}
                      >
                        {fmtUSD(row.total_pnl)}
                      </td>
                      <td
                        className={`p-2 text-right ${row.avg_pnl < 0 ? 'text-rose-500' : 'text-emerald-500'}`}
                      >
                        {fmtUSD(row.avg_pnl)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Challenger shadows */}
      <div className="mt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Challenger Shadows
        </p>
        {challengers.length === 0 ? (
          <p className="text-xs text-slate-500">No shadow challengers running.</p>
        ) : (
          <div className="space-y-1.5">
            {challengers.map((c) => {
              const hasShadow = (c.shadow_trades ?? 0) > 0
              return (
                <div
                  key={c.challenger_id}
                  className="rounded-lg border border-slate-300 px-3 py-2 dark:border-slate-800"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2 truncate">
                      <span
                        className={`h-2 w-2 shrink-0 rounded-full ${c.running ? 'bg-emerald-500' : 'bg-slate-400'}`}
                      />
                      <span className="truncate font-mono text-xs text-slate-700 dark:text-slate-300">
                        {c.strategy || `challenger ${c.challenger_id}`}
                      </span>
                      {c.beats_baseline_shadow ? (
                        <span className="shrink-0 rounded-full bg-emerald-500/10 px-1.5 text-[10px] font-bold text-emerald-500">
                          beats baseline
                        </span>
                      ) : null}
                    </span>
                    <span className="shrink-0 font-mono text-xs tabular-nums text-slate-500 dark:text-slate-400">
                      {c.fills}/{c.max_fills} fills
                    </span>
                  </div>
                  {/* Real shadow-trade evidence — what the config actually did on live data. */}
                  {hasShadow ? (
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 pl-4 font-mono text-[11px] text-slate-500 dark:text-slate-400">
                      <span>shadow trades: {c.shadow_trades}</span>
                      <span>
                        win: {c.shadow_win_rate != null ? `${(c.shadow_win_rate * 100).toFixed(0)}%` : '--'}
                      </span>
                      <span className={(c.shadow_pnl ?? 0) < 0 ? 'text-rose-500' : 'text-emerald-500'}>
                        pnl: {c.shadow_pnl != null ? fmtUSD(c.shadow_pnl) : '--'}
                      </span>
                    </div>
                  ) : (
                    <p className="mt-1 pl-4 text-[11px] text-slate-400">
                      warming up — no shadow trades yet
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Parameter Evolution — pending GitOps PRs that tune live params */}
      <div className="mt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Parameter Evolution — Pending PRs
        </p>
        {pendingPRs.length === 0 ? (
          <p className="text-xs text-slate-500">
            No pending parameter changes. The learning loop opens a PR when it has evidence to
            tune a parameter.
          </p>
        ) : (
          <div className="max-h-48 overflow-y-auto rounded-lg border border-slate-300 dark:border-slate-800">
            <table className="w-full text-xs font-mono">
              <thead className="bg-slate-100 dark:bg-slate-800/50">
                <tr className="text-left">
                  <th className="p-2">Parameter</th>
                  <th className="p-2 text-right">Current</th>
                  <th className="p-2 text-right">Proposed</th>
                  <th className="p-2">Reason</th>
                </tr>
              </thead>
              <tbody>
                {pendingPRs.slice(0, 12).map((p) => (
                  <tr
                    key={p.parameter}
                    className="border-t border-slate-200 dark:border-slate-800"
                  >
                    <td className="p-2">{p.parameter}</td>
                    <td className="p-2 text-right text-slate-500">{p.previous_value ?? '--'}</td>
                    <td className="p-2 text-right text-amber-500">{p.proposed_value ?? '--'}</td>
                    <td className="p-2 text-slate-500 truncate" title={p.reason}>
                      {p.reason || '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
