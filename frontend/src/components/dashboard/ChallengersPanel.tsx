'use client'

import { API_ENDPOINTS } from '@/lib/apiClient'
import { usePolledApi } from '@/hooks/usePolledApi'
import { LEARNING_REFRESH_MS } from '@/lib/grade-colors'
import { cardClass, errorTextClass, mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { sentimentTextClass, TONE_DOT, type Tone } from '@/lib/design/sentiment'
import { formatPercent, formatTimeAgo, signedUSD } from '@/lib/formatters'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { Badge } from '@/components/ui/badge'
import { Meter } from '@/components/ui/meter'
import { StatTile } from '@/components/ui/stat-tile'
import { cn } from '@/lib/utils'

// One closed shadow round-trip — the live FLOW of what the strategy actually did.
export type ShadowTrade = {
  symbol: string
  direction: string
  pnl: number
  entry_price?: number
  exit_price?: number
  timestamp?: string
}

// A shadow ChallengerAgent (GET /dashboard/challengers). Carries the REAL
// own-vs-baseline shadow evidence PLUS liveness, promotion progress (including
// the named unmet criteria) and the recent-trade flow.
export type ChallengerInfo = {
  challenger_id: string
  fills: number
  max_fills: number
  running: boolean
  strategy?: string
  shadow_trades?: number
  shadow_win_rate?: number
  shadow_pnl?: number
  shadow_sharpe?: number
  beats_baseline_shadow?: boolean
  baseline_shadow_trades?: number
  baseline_shadow_win_rate?: number
  baseline_shadow_pnl?: number
  min_shadow_trades?: number
  min_shadow_win_rate?: number
  promotion_blockers?: string[]
  shadow_proposal_emitted?: boolean
  ticks_observed?: number
  last_tick_at?: string | null
  last_shadow_trade_at?: string | null
  open_shadow_positions?: number
  recent_shadow_trades?: ShadowTrade[]
  latest_grade?: { win_rate?: number; avg_pnl?: number; fills?: number } | null
  // Durable graduation state — set by ProposalApplier once an approved promotion
  // advances this strategy SHADOW→CANARY. Survives restarts (Redis-backed).
  graduated?: boolean
  graduated_at?: string | null
  // BACKEND-decided place in the learning loop + edge over baseline. The UI only
  // renders these — it never re-derives the state (see challengerLearningStatus).
  learning_status?: string
  shadow_edge?: number | null
}

// The backend's ChallengerLearningStatus enum → a Tone for chips/dots. The
// status itself is decided server-side; this map is pure presentation.
export const CHALLENGER_STATUS_TONE: Record<string, Tone> = {
  graduated: 'success',
  promotion_proposed: 'success',
  eligible: 'success',
  building: 'warning',
  warming: 'neutral',
}

// Single accessor for a challenger's loop state: trust the backend's
// learning_status, falling back to deriving it only for older payloads that
// predate the field. Both challenger views call this — neither re-implements
// the decision.
export function challengerLearningStatus(c: ChallengerInfo): string {
  if (c.learning_status) return c.learning_status
  if (c.graduated) return 'graduated'
  if (c.shadow_proposal_emitted) return 'promotion_proposed'
  const trades = c.shadow_trades ?? 0
  if ((c.promotion_blockers?.length ?? 1) === 0 && trades > 0) return 'eligible'
  if (trades > 0) return 'building'
  return 'warming'
}

const relTime = (iso: string | null | undefined): string =>
  iso ? formatTimeAgo(iso) : UI_COPY.challengers.never

// "live" while the challenger has observed a tick in the last STALE window —
// shadow trades run off the raw price stream, so a live challenger should tick
// every few seconds; longer means the stream (or the challenger) has stalled.
const CHALLENGER_STALE_SECONDS = 120
const isFresh = (iso: string | null | undefined): boolean => {
  if (!iso) return false
  const then = new Date(iso).getTime()
  if (!Number.isFinite(then)) return false
  return (Date.now() - then) / 1000 <= CHALLENGER_STALE_SECONDS
}

const compactStatClass = 'p-2 sm:p-2'

// backend ChallengerLearningStatus → the card's narrative line / badge label.
// Pure presentation; the state itself is decided server-side.
const STATUS_NARRATIVE: Record<string, string> = {
  graduated: UI_COPY.challengers.statusGraduated,
  promotion_proposed: UI_COPY.challengers.statusPromoted,
  eligible: UI_COPY.challengers.statusEligible,
  building: UI_COPY.challengers.statusBuilding,
  warming: UI_COPY.challengers.statusWarming,
}
const STATUS_BADGE: Record<string, string> = {
  graduated: UI_COPY.challengers.badgeGraduated,
  promotion_proposed: UI_COPY.challengers.badgePromoted,
  eligible: UI_COPY.challengers.badgeEligible,
  building: UI_COPY.challengers.badgeWarming,
  warming: UI_COPY.challengers.badgeWarming,
}

function ChallengerCard({ c }: { c: ChallengerInfo }) {
  const shadowTrades = c.shadow_trades ?? 0
  const minTrades = c.min_shadow_trades ?? 40
  const live = c.last_tick_at ? isFresh(c.last_tick_at) : c.running
  const progressPct = Math.min(100, Math.round((shadowTrades / minTrades) * 100))
  const recent = c.recent_shadow_trades ?? []
  const blockers = c.promotion_blockers ?? []

  // The BACKEND decides the loop state (learning_status); the card only renders
  // it — narrative line, badge label, and badge tone all key off this one value.
  const ls = challengerLearningStatus(c)
  const status = STATUS_NARRATIVE[ls] ?? UI_COPY.challengers.statusWarming
  const badgeTone = CHALLENGER_STATUS_TONE[ls] ?? 'warning'
  const badgeLabel =
    ls === 'building' && blockers.length > 0
      ? `${blockers.length} requirement${blockers.length === 1 ? '' : 's'} unmet`
      : (STATUS_BADGE[ls] ?? UI_COPY.challengers.badgeWarming)

  return (
    <div className={cardClass}>
      {/* Identity row */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <span
            className={cn('h-2 w-2 shrink-0 rounded-full', live ? TONE_DOT.success : TONE_DOT.neutral)}
            title={live ? UI_COPY.challengers.dotLive : UI_COPY.challengers.dotStale}
          />
          <span className="font-mono text-sm font-semibold text-foreground">
            {c.strategy || `challenger ${c.challenger_id}`}
          </span>
          <Badge tone={badgeTone} size="xs" pill className="font-bold">
            {badgeLabel}
          </Badge>
        </span>
        <span className="font-mono text-2xs tabular-nums text-muted-foreground">
          id {c.challenger_id} · ticked {relTime(c.last_tick_at)} · {c.ticks_observed ?? 0} ticks seen
        </span>
      </div>
      <p className={cn(mutedClass, 'mt-1')}>{status}</p>

      {/* Own record vs baseline, side by side */}
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatTile
          label={UI_COPY.challengers.statTrades}
          value={String(shadowTrades)}
          valueClassName="mt-0.5 text-sm font-bold"
          className={compactStatClass}
        />
        <StatTile
          label={UI_COPY.challengers.statWinRate}
          value={formatPercent(c.shadow_win_rate, { decimals: 0 })}
          valueClassName="mt-0.5 text-sm font-bold"
          className={compactStatClass}
        />
        <StatTile
          label={UI_COPY.challengers.statPnl}
          value={signedUSD(c.shadow_pnl)}
          valueClassName={cn('mt-0.5 text-sm font-bold', sentimentTextClass(c.shadow_pnl ?? 0))}
          className={compactStatClass}
        />
        <StatTile
          label={UI_COPY.challengers.statSharpe}
          value={c.shadow_sharpe != null ? c.shadow_sharpe.toFixed(2) : NO_DATA}
          valueClassName="mt-0.5 text-sm font-bold"
          className={compactStatClass}
        />
      </div>
      {c.baseline_shadow_trades != null && (
        <p className="mt-1.5 font-mono text-2xs text-muted-foreground">
          baseline on the same ticks: {c.baseline_shadow_trades} trades ·{' '}
          {formatPercent(c.baseline_shadow_win_rate, { decimals: 0 })} win ·{' '}
          {signedUSD(c.baseline_shadow_pnl)}
          {c.beats_baseline_shadow != null && (
            <span className={sentimentTextClass(c.beats_baseline_shadow ? 1 : -1)}>
              {' '}
              — challenger {c.beats_baseline_shadow ? 'ahead' : 'behind'}
            </span>
          )}
        </p>
      )}

      {/* Promotion requirements — the full (hard) bar, with progress */}
      <div className="mt-3">
        <div className="mb-0.5 flex justify-between font-mono text-3xs text-muted-foreground/70">
          <span>{UI_COPY.challengers.progressLabel}</span>
          <span>
            {Math.min(shadowTrades, minTrades)}/{minTrades}
          </span>
        </div>
        <Meter
          value={progressPct}
          label={UI_COPY.challengers.progressLabel}
          className="h-1"
          fillClassName={progressPct >= 100 ? TONE_DOT.success : TONE_DOT.warning}
        />
        {blockers.length > 0 && (
          <ul className="mt-1.5 space-y-0.5">
            {blockers.map((b) => (
              <li key={b} className="flex items-center gap-1.5 text-2xs text-muted-foreground">
                <span className="text-warning">○</span> {b}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Live trade flow — the recent shadow round-trips */}
      {recent.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 font-mono text-3xs uppercase tracking-caps text-muted-foreground/70">
            {UI_COPY.challengers.recentTrades}
          </p>
          <div className="space-y-0.5 font-mono text-2xs">
            {recent.map((t, i) => (
              <div
                key={`${t.symbol}-${t.timestamp ?? i}`}
                className="flex items-center justify-between gap-2 text-muted-foreground"
              >
                <span className="truncate">
                  {t.direction === 'long' ? '▲' : '▼'} {t.direction} {t.symbol}
                  {t.entry_price != null && t.exit_price != null && (
                    <span className="text-muted-foreground/70"> {t.entry_price} → {t.exit_price}</span>
                  )}
                </span>
                <span className="shrink-0 tabular-nums">
                  <span className={sentimentTextClass(t.pnl)}>{signedUSD(t.pnl)}</span>
                  <span className="text-muted-foreground/70"> · {relTime(t.timestamp)}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Live (real-fill) grading state */}
      <p className="mt-3 font-mono text-3xs text-muted-foreground/70">
        {(c.fills ?? 0) === 0
          ? `0/${c.max_fills} live fills — live grading starts when the pipeline trades; shadow trades above run on raw price ticks regardless.`
          : c.latest_grade
            ? `live grade: ${formatPercent(c.latest_grade.win_rate, { decimals: 0 })} win over ${c.latest_grade.fills ?? c.fills} fills · ${c.fills}/${c.max_fills} fills`
            : `${c.fills}/${c.max_fills} live fills`}
      </p>
    </div>
  )
}

/** Full-page view: every shadow challenger with its complete evidence trail —
 *  own record, baseline comparison, the named promotion requirements still
 *  unmet, and the live flow of its recent shadow trades. */
export function ChallengersPanel() {
  const { data, error, loaded } = usePolledApi<{ challengers: ChallengerInfo[] }>(
    API_ENDPOINTS.DASHBOARD_CHALLENGERS,
    LEARNING_REFRESH_MS,
  )
  const challengers = data?.challengers ?? []

  return (
    <div className="space-y-3">
      <div className={cardClass}>
        <div className="flex items-center justify-between gap-2">
          <p className={sectionTitleClass}>{UI_COPY.challengers.title}</p>
          {error ? (
            <span className={errorTextClass}>err: {error}</span>
          ) : (
            <span className="font-mono text-xs text-muted-foreground/70">
              {challengers.length} {UI_COPY.challengers.running}
            </span>
          )}
        </div>
        <p className={cn(mutedClass, 'mt-1')}>{UI_COPY.challengers.description}</p>
      </div>

      {!loaded ? (
        <p className={cn(cardClass, 'text-xs text-muted-foreground')}>{UI_COPY.loading.challengers}</p>
      ) : challengers.length === 0 ? (
        <p className={cn(cardClass, 'text-xs text-muted-foreground')}>
          {UI_COPY.challengers.emptyState}
        </p>
      ) : (
        challengers.map((c) => <ChallengerCard key={c.challenger_id} c={c} />)
      )}
    </div>
  )
}
