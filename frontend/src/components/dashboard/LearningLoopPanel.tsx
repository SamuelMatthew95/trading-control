'use client'

import Link from 'next/link'

import { API_ENDPOINTS } from '@/lib/apiClient'
import { usePolledApi } from '@/hooks/usePolledApi'
import { cardClass, errorTextClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { LEARNING_REFRESH_MS, gradeColor } from '@/lib/grade-colors'
import { sentimentTextClass } from '@/lib/design/sentiment'
import { signedUSD } from '@/lib/formatters'
import { agentDisplayName } from '@/constants/agents'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { cn } from '@/lib/utils'
import type { ChallengerInfo } from '@/components/dashboard/ChallengersPanel'

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

// A pending parameter-change PR artifact (GET /learning/pending-param-changes).
type PendingParamChange = {
  parameter: string
  previous_value: number | string | null
  proposed_value: number | string | null
  reason: string
  timestamp: string | null
}

const COPY = UI_COPY.learningLoop

const subTableWrapClass = 'max-h-48 overflow-y-auto rounded-lg border'
const subTableClass = 'w-full font-mono text-xs'
const subTableHeadClass = 'bg-muted/60'
const tileClass = 'rounded-lg border p-3'
const tileLabelClass = 'text-xs text-muted-foreground'

export function LearningLoopPanel() {
  const { data: state, error } = usePolledApi<LearningLoopState>(
    API_ENDPOINTS.LEARNING_LOOP,
    LEARNING_REFRESH_MS,
  )
  // Challenger list and pending PRs are best-effort — their absence must not
  // blank the panel (usePolledApi keeps last good data through failures).
  const { data: challengerData } = usePolledApi<{ challengers: ChallengerInfo[] }>(
    API_ENDPOINTS.DASHBOARD_CHALLENGERS,
    LEARNING_REFRESH_MS,
  )
  const { data: prData } = usePolledApi<{ items: PendingParamChange[] }>(
    API_ENDPOINTS.LEARNING_PENDING_PARAM_CHANGES,
    LEARNING_REFRESH_MS,
  )
  const challengers = challengerData?.challengers ?? []
  const pendingPRs = prData?.items ?? []

  const cp = state?.control_plane ?? null
  const grade = state?.latest_grade ?? null
  const proposals = state?.recent_proposals ?? []
  const attribution = state?.loss_attribution ?? []
  const appliedCount = proposals.filter((p) => p.applied).length
  const pendingCount = proposals.length - appliedCount
  const promotionsProposed = challengers.filter((c) => c.shadow_proposal_emitted).length

  return (
    <div className={cardClass}>
      <div className="mb-3 flex items-center justify-between">
        <p className={sectionTitleClass}>{COPY.title}</p>
        {error ? (
          <span className={errorTextClass}>err: {error}</span>
        ) : (
          <span className="text-xs text-muted-foreground/70">
            {state?.timestamp ? new Date(state.timestamp).toLocaleTimeString() : NO_DATA}
          </span>
        )}
      </div>

      {/* Tile row: grade + control plane */}
      <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-4">
        <div className={tileClass}>
          <p className={tileLabelClass}>{COPY.latestGrade}</p>
          <p className={cn('font-mono text-2xl font-semibold', gradeColor(grade?.grade ?? null))}>
            {grade?.grade ?? NO_DATA}
          </p>
          <p className="font-mono text-xs text-muted-foreground">
            {grade?.score_pct != null ? `${grade.score_pct.toFixed(1)}%` : NO_DATA}
          </p>
        </div>
        <div className={tileClass}>
          <p className={tileLabelClass}>{COPY.tradingPaused}</p>
          <p className={cn('font-mono text-lg font-bold', cp?.trading_paused ? 'text-danger' : 'text-success')}>
            {cp?.trading_paused ? COPY.paused : COPY.live}
          </p>
          {cp?.trading_paused && cp.trading_paused_reason ? (
            <p className="truncate text-xs text-muted-foreground" title={cp.trading_paused_reason}>
              {cp.trading_paused_reason}
            </p>
          ) : null}
        </div>
        <div className={tileClass}>
          <p className={tileLabelClass}>{COPY.signalWeight}</p>
          <p className="font-mono text-lg font-bold tabular-nums">
            {cp ? cp.signal_weight_scale.toFixed(3) : NO_DATA}
          </p>
          <p className="text-xs text-muted-foreground">
            {cp && cp.signal_weight_scale < 1 ? COPY.dampened : COPY.full}
          </p>
        </div>
        <div className={tileClass}>
          <p className={tileLabelClass}>{COPY.proposals}</p>
          <p className="font-mono text-lg font-bold tabular-nums">
            <span className="text-success">{appliedCount}</span>
            <span className="text-muted-foreground/70"> / </span>
            <span className="text-warning">{pendingCount}</span>
          </p>
          <p className="text-xs text-muted-foreground">{COPY.appliedPending}</p>
        </div>
      </div>

      {/* Suspended agents (control-plane effect) — only when any are suspended */}
      {cp && cp.suspended_agents.length > 0 && (
        <div className="mb-4">
          <p className={cn(sectionTitleClass, 'mb-2')}>{COPY.suspendedAgents}</p>
          <div className="flex flex-wrap gap-2">
            {cp.suspended_agents.map((s) => (
              <span
                key={s.agent_name}
                className="rounded-full border border-danger/30 bg-danger/10 px-2 py-0.5 font-mono text-xs text-danger"
              >
                {agentDisplayName(s.agent_name)}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Proposals list */}
      <div className="mb-4">
        <p className={cn(sectionTitleClass, 'mb-2')}>{COPY.recentProposals}</p>
        {proposals.length === 0 ? (
          <p className="text-xs text-muted-foreground">{COPY.noProposals}</p>
        ) : (
          <div className={subTableWrapClass}>
            <table className={subTableClass}>
              <thead className={subTableHeadClass}>
                <tr className="text-left">
                  <th className="p-2">{COPY.columns.type}</th>
                  <th className="p-2">{COPY.columns.action}</th>
                  <th className="p-2">{COPY.columns.state}</th>
                  <th className="p-2">{COPY.columns.when}</th>
                </tr>
              </thead>
              <tbody>
                {proposals.slice(0, 10).map((p) => (
                  <tr key={p.trace_id} className="border-t">
                    <td className="p-2">{p.proposal_type ?? NO_DATA}</td>
                    <td className="p-2 text-muted-foreground">{p.action ?? p.message ?? NO_DATA}</td>
                    <td className="p-2">
                      {p.applied ? (
                        <span className="text-success">{COPY.applied}</span>
                      ) : (
                        <span className="text-warning">{COPY.pending}</span>
                      )}
                    </td>
                    <td className="p-2 text-muted-foreground">
                      {p.timestamp ? new Date(p.timestamp).toLocaleTimeString() : NO_DATA}
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
        <p className={cn(sectionTitleClass, 'mb-2')}>{COPY.lossAttribution}</p>
        {attribution.length === 0 ? (
          <p className="text-xs text-muted-foreground">{COPY.noClosedTrades}</p>
        ) : (
          <div className={subTableWrapClass}>
            <table className={subTableClass}>
              <thead className={subTableHeadClass}>
                <tr className="text-left">
                  <th className="p-2">{COPY.columns.symbol}</th>
                  <th className="p-2">{COPY.columns.signal}</th>
                  <th className="p-2 text-right">{COPY.columns.trades}</th>
                  <th className="p-2 text-right">{COPY.columns.losses}</th>
                  <th className="p-2 text-right">{COPY.columns.totalPnl}</th>
                  <th className="p-2 text-right">{COPY.columns.avgPnl}</th>
                </tr>
              </thead>
              <tbody>
                {attribution.slice(0, 12).map((row) => (
                  <tr key={`${row.symbol}-${row.signal_type}`} className="border-t">
                    <td className="p-2">{row.symbol}</td>
                    <td className="p-2 text-muted-foreground">{row.signal_type}</td>
                    <td className="p-2 text-right">{row.trades}</td>
                    <td className="p-2 text-right">{row.losses}</td>
                    <td className={cn('p-2 text-right', sentimentTextClass(row.total_pnl))}>
                      {signedUSD(row.total_pnl)}
                    </td>
                    <td className={cn('p-2 text-right', sentimentTextClass(row.avg_pnl))}>
                      {signedUSD(row.avg_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Challenger shadows — summary only; the full evidence trail lives on
          its own page so each challenger can be followed in detail. */}
      <div className="mt-4">
        <p className={cn(sectionTitleClass, 'mb-1')}>{COPY.challengerShadows}</p>
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2">
          <span className="font-mono text-xs text-foreground/70">
            {challengers.length === 0
              ? COPY.noChallengers
              : `${challengers.length} ${COPY.running} · ${challengers.filter((c) => c.beats_baseline_shadow).length} ${COPY.beatingBaseline} · ${promotionsProposed} ${promotionsProposed === 1 ? COPY.promotionProposedSingular : COPY.promotionProposedPlural}`}
          </span>
          <Link href="/dashboard/challengers" className="text-xs font-semibold text-brand hover:underline">
            {COPY.followChallengers}
          </Link>
        </div>
      </div>

      {/* Parameter Evolution — pending GitOps PRs that tune live params */}
      <div className="mt-4">
        <p className={cn(sectionTitleClass, 'mb-2')}>{COPY.paramEvolution}</p>
        {pendingPRs.length === 0 ? (
          <p className="text-xs text-muted-foreground">{COPY.noPendingParams}</p>
        ) : (
          <div className={subTableWrapClass}>
            <table className={subTableClass}>
              <thead className={subTableHeadClass}>
                <tr className="text-left">
                  <th className="p-2">{COPY.columns.parameter}</th>
                  <th className="p-2 text-right">{COPY.columns.current}</th>
                  <th className="p-2 text-right">{COPY.columns.proposed}</th>
                  <th className="p-2">{COPY.columns.reason}</th>
                </tr>
              </thead>
              <tbody>
                {pendingPRs.slice(0, 12).map((p) => (
                  <tr key={p.parameter} className="border-t">
                    <td className="p-2">{p.parameter}</td>
                    <td className="p-2 text-right text-muted-foreground">{p.previous_value ?? NO_DATA}</td>
                    <td className="p-2 text-right text-warning">{p.proposed_value ?? NO_DATA}</td>
                    <td className="truncate p-2 text-muted-foreground" title={p.reason}>
                      {p.reason || NO_DATA}
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
