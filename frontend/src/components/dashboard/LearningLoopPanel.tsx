'use client'

import { useEffect, useState } from 'react'

import { API_ENDPOINTS, apiFetch } from '@/lib/apiClient'
import { LEARNING_REFRESH_MS, gradeColor } from '@/lib/grade-colors'

type SelfCorrection = {
  anomaly_detected?: boolean
  z_score?: number
  direction?: string
  baseline_mean?: number
  baseline_std?: number
  baseline_samples?: number
  trajectory?: { slope?: number; direction?: string; decaying?: boolean }
  attribution?: { dimension: string; delta: number }[]
  message?: string
}

type LatestGrade = {
  trace_id: string
  grade: string | null
  score_pct: number | null
  metrics: Record<string, number>
  self_correction?: SelfCorrection | null
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


const fmtUSD = (n: number): string =>
  (n >= 0 ? '+' : '') + n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

const trajectoryTone = (direction?: string): string =>
  direction === 'decaying'
    ? 'bg-rose-500/10 text-rose-500'
    : direction === 'improving'
      ? 'bg-emerald-500/10 text-emerald-500'
      : 'bg-slate-500/10 text-slate-500'

export function LearningLoopPanel() {
  const [state, setState] = useState<LearningLoopState | null>(null)
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
  const sc = grade?.self_correction ?? null
  const hasSelfCorrection = Boolean(sc && (sc.baseline_samples != null || sc.trajectory != null))
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
          <p className={`text-2xl font-mono font-black ${gradeColor(grade?.grade ?? null)}`}>
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

      {/* Self-correction diagnostic — grade anomaly detection + trajectory */}
      <div className="mb-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Self-Correction
        </p>
        {hasSelfCorrection && sc ? (
          <div className="rounded-lg border border-slate-300 p-3 dark:border-slate-800">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span
                className={`rounded px-2 py-0.5 text-xs font-mono font-bold ${trajectoryTone(sc.trajectory?.direction)}`}
              >
                trend: {sc.trajectory?.direction ?? '--'}
              </span>
              {sc.anomaly_detected ? (
                <span
                  className={`rounded px-2 py-0.5 text-xs font-mono font-bold ${sc.direction === 'negative_drop' ? 'bg-rose-500/10 text-rose-500' : 'bg-amber-500/10 text-amber-500'}`}
                >
                  {sc.direction} (z={sc.z_score != null ? sc.z_score.toFixed(2) : '--'})
                </span>
              ) : (
                <span className="rounded px-2 py-0.5 text-xs font-mono text-slate-500">
                  no anomaly
                </span>
              )}
              <span className="text-xs font-mono text-slate-500">
                μ={sc.baseline_mean != null ? sc.baseline_mean.toFixed(3) : '--'}±
                {sc.baseline_std != null ? sc.baseline_std.toFixed(3) : '--'} (n=
                {sc.baseline_samples ?? 0})
              </span>
            </div>
            {sc.attribution && sc.attribution.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {sc.attribution.slice(0, 4).map((a) => (
                  <span
                    key={a.dimension}
                    className="rounded bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                  >
                    {a.dimension} {a.delta >= 0 ? '+' : ''}
                    {a.delta.toFixed(3)}
                  </span>
                ))}
              </div>
            ) : null}
            {sc.message ? (
              <p className="mt-2 text-xs text-slate-500" title={sc.message}>
                {sc.message}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-slate-500">
            Calibrating — diagnostics appear after a few grade cycles.
          </p>
        )}
      </div>

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
    </div>
  )
}
