'use client'

import { useEffect, useState } from 'react'

import { API_ENDPOINTS, apiFetch } from '@/lib/apiClient'
import { LEARNING_REFRESH_MS } from '@/lib/grade-colors'
import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
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
}

const fmtUSD = (n: number | null | undefined): string => {
  if (n == null || !Number.isFinite(n)) return '--'
  return (n >= 0 ? '+' : '') + n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

const fmtPct = (n: number | null | undefined): string =>
  n == null || !Number.isFinite(n) ? '--' : `${(n * 100).toFixed(0)}%`

// Compact "12s ago" / "3m ago" / "2h ago" — stale data is obviously stale.
const relTime = (iso: string | null | undefined): string => {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  if (!Number.isFinite(then)) return '--'
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (secs < 60) return `${secs}s ago`
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

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

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'success' | 'danger' }) {
  return (
    <div className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p
        className={cn(
          'font-mono text-sm font-bold tabular-nums text-slate-900 dark:text-slate-100',
          tone === 'success' && 'text-success',
          tone === 'danger' && 'text-danger',
        )}
      >
        {value}
      </p>
    </div>
  )
}

function ChallengerCard({ c }: { c: ChallengerInfo }) {
  const shadowTrades = c.shadow_trades ?? 0
  const minTrades = c.min_shadow_trades ?? 40
  const live = c.last_tick_at ? isFresh(c.last_tick_at) : c.running
  const progressPct = Math.min(100, Math.round((shadowTrades / minTrades) * 100))
  const recent = c.recent_shadow_trades ?? []
  const blockers = c.promotion_blockers ?? []
  const eligible = blockers.length === 0 && shadowTrades > 0

  // Connected status narrative — WHY it is where it is, in words.
  let status: string
  if (c.shadow_proposal_emitted) {
    status = 'Promotion fired — cleared every bar (trades, win rate, +PnL, +Sharpe, beats baseline).'
  } else if (eligible) {
    status = 'Eligible — promotion proposal fires on the next confirming tick.'
  } else if (shadowTrades > 0) {
    status = 'Building its record — every unmet requirement is listed below.'
  } else {
    status = 'Warming up — no shadow round-trips closed yet.'
  }

  return (
    <div className={cardClass}>
      {/* Identity row */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <span
            className={cn('h-2 w-2 shrink-0 rounded-full', live ? 'bg-success' : 'bg-slate-400')}
            title={live ? 'live — ticking' : 'stale — no recent tick'}
          />
          <span className="font-mono text-sm font-semibold text-slate-900 dark:text-slate-100">
            {c.strategy || `challenger ${c.challenger_id}`}
          </span>
          {c.shadow_proposal_emitted ? (
            <span className="shrink-0 rounded-full bg-success/10 px-2 py-0.5 text-[10px] font-bold text-success">
              promotion proposed
            </span>
          ) : eligible ? (
            <span className="shrink-0 rounded-full bg-success/10 px-2 py-0.5 text-[10px] font-bold text-success">
              eligible
            </span>
          ) : (
            <span className="shrink-0 rounded-full bg-warning/10 px-2 py-0.5 text-[10px] font-bold text-warning">
              {blockers.length > 0 ? `${blockers.length} requirement${blockers.length === 1 ? '' : 's'} unmet` : 'warming up'}
            </span>
          )}
        </span>
        <span className="font-mono text-[11px] tabular-nums text-slate-500 dark:text-slate-400">
          id {c.challenger_id} · ticked {relTime(c.last_tick_at)} · {c.ticks_observed ?? 0} ticks seen
        </span>
      </div>
      <p className={cn(mutedClass, 'mt-1')}>{status}</p>

      {/* Own record vs baseline, side by side */}
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Shadow trades" value={String(shadowTrades)} />
        <Stat label="Win rate" value={fmtPct(c.shadow_win_rate)} />
        <Stat
          label="Shadow PnL"
          value={fmtUSD(c.shadow_pnl)}
          tone={(c.shadow_pnl ?? 0) >= 0 ? 'success' : 'danger'}
        />
        <Stat label="Sharpe" value={c.shadow_sharpe != null ? c.shadow_sharpe.toFixed(2) : '--'} />
      </div>
      {c.baseline_shadow_trades != null && (
        <p className="mt-1.5 font-mono text-[11px] text-slate-500 dark:text-slate-400">
          baseline on the same ticks: {c.baseline_shadow_trades} trades ·{' '}
          {fmtPct(c.baseline_shadow_win_rate)} win · {fmtUSD(c.baseline_shadow_pnl)}
          {c.beats_baseline_shadow != null && (
            <span className={c.beats_baseline_shadow ? 'text-success' : 'text-danger'}>
              {' '}
              — challenger {c.beats_baseline_shadow ? 'ahead' : 'behind'}
            </span>
          )}
        </p>
      )}

      {/* Promotion requirements — the full (hard) bar, with progress */}
      <div className="mt-3">
        <div className="mb-0.5 flex justify-between font-mono text-[10px] text-slate-400">
          <span>shadow trades toward eligibility</span>
          <span>
            {Math.min(shadowTrades, minTrades)}/{minTrades}
          </span>
        </div>
        <div className="h-1 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
          <div
            className={cn('h-full rounded-full', progressPct >= 100 ? 'bg-success' : 'bg-warning')}
            style={{ width: `${progressPct}%` }}
          />
        </div>
        {blockers.length > 0 && (
          <ul className="mt-1.5 space-y-0.5">
            {blockers.map((b) => (
              <li key={b} className="flex items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                <span className="text-warning">○</span> {b}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Live trade flow — the recent shadow round-trips */}
      {recent.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-slate-400">
            recent shadow trades
          </p>
          <div className="space-y-0.5 font-mono text-[11px]">
            {recent.map((t, i) => (
              <div
                key={`${t.symbol}-${t.timestamp ?? i}`}
                className="flex items-center justify-between gap-2 text-slate-500 dark:text-slate-400"
              >
                <span className="truncate">
                  {t.direction === 'long' ? '▲' : '▼'} {t.direction} {t.symbol}
                  {t.entry_price != null && t.exit_price != null && (
                    <span className="text-slate-400"> {t.entry_price} → {t.exit_price}</span>
                  )}
                </span>
                <span className="shrink-0 tabular-nums">
                  <span className={t.pnl < 0 ? 'text-danger' : 'text-success'}>{fmtUSD(t.pnl)}</span>
                  <span className="text-slate-400"> · {relTime(t.timestamp)}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Live (real-fill) grading state */}
      <p className="mt-3 font-mono text-[10px] text-slate-400">
        {(c.fills ?? 0) === 0
          ? `0/${c.max_fills} live fills — live grading starts when the pipeline trades; shadow trades above run on raw price ticks regardless.`
          : c.latest_grade
            ? `live grade: ${fmtPct(c.latest_grade.win_rate)} win over ${c.latest_grade.fills ?? c.fills} fills · ${c.fills}/${c.max_fills} fills`
            : `${c.fills}/${c.max_fills} live fills`}
      </p>
    </div>
  )
}

/** Full-page view: every shadow challenger with its complete evidence trail —
 *  own record, baseline comparison, the named promotion requirements still
 *  unmet, and the live flow of its recent shadow trades. */
export function ChallengersPanel() {
  const [challengers, setChallengers] = useState<ChallengerInfo[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const ch = await apiFetch<{ challengers: ChallengerInfo[] }>(
          API_ENDPOINTS.DASHBOARD_CHALLENGERS,
        )
        if (!cancelled) {
          setChallengers(ch.challengers ?? [])
          setError(null)
          setLoaded(true)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'fetch_failed')
          setLoaded(true)
        }
      }
    }
    load()
    const id = window.setInterval(load, LEARNING_REFRESH_MS)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  return (
    <div className="space-y-3">
      <div className={cardClass}>
        <div className="flex items-center justify-between gap-2">
          <p className={sectionTitleClass}>Challenger Shadows</p>
          {error ? (
            <span className="font-mono text-xs text-danger">err: {error}</span>
          ) : (
            <span className="font-mono text-xs text-slate-400">{challengers.length} running</span>
          )}
        </div>
        <p className={cn(mutedClass, 'mt-1')}>
          Rival strategies shadow-trading the live price stream — they never place real orders.
          Promotion requires the full bar: enough shadow trades, a minimum win rate, positive PnL,
          positive Sharpe, <em>and</em> beating the baseline on the same ticks. When one clears it,
          a promotion proposal lands on the <span className="font-medium">Proposals</span> page.
        </p>
      </div>

      {!loaded ? (
        <p className={cn(cardClass, 'text-xs text-slate-500')}>Loading challengers…</p>
      ) : challengers.length === 0 ? (
        <p className={cn(cardClass, 'text-xs text-slate-500')}>
          No shadow challengers running. They spawn from approved challenger promotions or
          new-agent proposals on the Proposals page.
        </p>
      ) : (
        challengers.map((c) => <ChallengerCard key={c.challenger_id} c={c} />)
      )}
    </div>
  )
}
