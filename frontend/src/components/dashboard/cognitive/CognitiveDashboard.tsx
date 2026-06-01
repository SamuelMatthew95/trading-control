'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  Activity,
  Brain,
  GitPullRequest,
  History,
  Radio,
  Workflow,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import {
  actionTone,
  fetchCognitiveEvents,
  fetchCognitiveState,
  gradeTone,
  signed,
  statusTone,
} from '@/lib/cognitive'
import type {
  CognitiveEvent,
  CognitiveSnapshot,
  QueueEntry,
  TradeTrace,
} from '@/types/cognitive'

const num = (obj: Record<string, unknown> | null | undefined, key: string): number => {
  const value = obj?.[key]
  return typeof value === 'number' ? value : Number(value ?? 0)
}
const str = (obj: Record<string, unknown> | null | undefined, key: string): string => {
  const value = obj?.[key]
  return value == null ? '' : String(value)
}

const TABS = [
  { id: 'command', label: 'Command Center', Icon: Activity },
  { id: 'agents', label: 'Cognitive Agents', Icon: Brain },
  { id: 'proposals', label: 'Proposals', Icon: GitPullRequest },
  { id: 'evolution', label: 'Evolution', Icon: History },
  { id: 'traces', label: 'Trace Explorer', Icon: Workflow },
  { id: 'events', label: 'Event Stream', Icon: Radio },
] as const

type TabId = (typeof TABS)[number]['id']

const card =
  'rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/40'
const chip =
  'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium'
const label = 'text-[11px] uppercase tracking-wide text-slate-400 dark:text-slate-500'

function Grade({ grade }: { grade: string | null | undefined }) {
  return <span className={cn(chip, gradeTone(grade))}>{grade || 'NR'}</span>
}

export function CognitiveDashboard() {
  const [tab, setTab] = useState<TabId>('command')
  const [snap, setSnap] = useState<CognitiveSnapshot | null>(null)
  const [events, setEvents] = useState<CognitiveEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [state, ev] = await Promise.all([fetchCognitiveState(), fetchCognitiveEvents(200)])
      setSnap(state)
      setEvents(ev)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'failed to load cognitive state')
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 10000)
    return () => clearInterval(timer)
  }, [load])

  if (error && !snap) {
    return (
      <div className={cn(card, 'text-sm text-rose-500')}>
        Could not reach the cognitive API: {error}
      </div>
    )
  }
  if (!snap) {
    return <div className={cn(card, 'animate-pulse text-sm text-slate-400')}>Loading the brain…</div>
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Cognitive Trading Brain
          </h1>
          <p className="text-xs text-slate-500">
            Deterministic loop · config v{snap.config.version} · {snap.event_count} events on the
            stream
          </p>
        </div>
        <nav className="flex flex-wrap gap-1">
          {TABS.map(({ id, label: tabLabel, Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition',
                tab === id
                  ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                  : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {tabLabel}
            </button>
          ))}
        </nav>
      </header>

      {tab === 'command' && <CommandCenter snap={snap} />}
      {tab === 'agents' && <AgentsPanel snap={snap} />}
      {tab === 'proposals' && <ProposalsPanel snap={snap} />}
      {tab === 'evolution' && <EvolutionPanel snap={snap} />}
      {tab === 'traces' && <TracesPanel traces={snap.traces} />}
      {tab === 'events' && <EventsPanel events={events} />}
    </div>
  )
}

function CommandCenter({ snap }: { snap: CognitiveSnapshot }) {
  const { health, decision } = snap
  const pipeline = health.proposal_pipeline
  const learning = health.learning
  const systemHealthy = learning.ungraded === 0 && health.decision.decisions_made > 0
  const latest = decision.latest

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className={card}>
          <div className={label}>System</div>
          <div
            className={cn(
              'mt-1 text-lg font-semibold',
              systemHealthy ? 'text-emerald-500' : 'text-amber-500',
            )}
          >
            {systemHealthy ? 'Healthy' : 'Warming up'}
          </div>
          <div className="mt-1 text-xs text-slate-500">
            {learning.trades_graded}/{learning.trades_closed} trades graded
          </div>
        </div>
        <div className={card}>
          <div className={label}>Top Decision</div>
          <div className="mt-1 flex items-center gap-2">
            <span className={cn(chip, actionTone(latest?.action))}>
              {(latest?.action || 'hold').toUpperCase()}
            </span>
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
              {latest ? signed(latest.score, 3) : '—'}
            </span>
          </div>
          <div className="mt-1 text-xs text-slate-500">
            band [{decision.sell_threshold}, {decision.buy_threshold}]
          </div>
        </div>
        <div className={card}>
          <div className={label}>Active Config</div>
          <div className="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-100">
            v{snap.config.version}
          </div>
          <div className="mt-1 text-xs text-slate-500">
            {pipeline.merged} merged · {pipeline.generated} proposed
          </div>
        </div>
        <div className={card}>
          <div className={label}>Proposal Pipeline</div>
          <div className="mt-1 text-sm text-slate-700 dark:text-slate-300">
            {pipeline.approved} approved · {pipeline.rejected} rejected
          </div>
          <div className="mt-1 text-xs text-slate-500">{pipeline.backtested} backtested</div>
        </div>
      </div>

      <div className={card}>
        <div className={cn(label, 'mb-2')}>Agent Health</div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(health.agents).map(([name, info]) => (
            <span
              key={name}
              className={cn(
                chip,
                info.status === 'healthy'
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                  : 'border-slate-500/20 bg-slate-500/10 text-slate-500',
              )}
            >
              {name} · {info.events}
            </span>
          ))}
        </div>
      </div>

      {latest && (
        <div className={card}>
          <div className={cn(label, 'mb-2')}>Decision Flow — score = Σ signalᵢ · weightᵢ</div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {Object.entries(latest.breakdown).map(([sig, contrib]) => (
              <span key={sig} className="rounded-md bg-slate-100 px-2 py-1 dark:bg-slate-800">
                {sig} {signed(contrib, 3)}
              </span>
            ))}
            <span className="text-slate-400">→</span>
            <span className="font-semibold">{signed(latest.score, 3)}</span>
            <span className="text-slate-400">→</span>
            <span className={cn(chip, actionTone(latest.action))}>
              {latest.action.toUpperCase()}
            </span>
          </div>
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        <div className={card}>
          <div className={cn(label, 'mb-2')}>Decision Quality (counterfactual)</div>
          <div className="flex gap-4 text-sm text-slate-700 dark:text-slate-300">
            <span>
              best-action rate{' '}
              <b>{((snap.learning.best_action_rate ?? 0) * 100).toFixed(0)}%</b>
            </span>
            <span>
              mean regret <b>{signed(snap.learning.mean_regret_pct ?? 0)}%</b>
            </span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            share of closed trades where the chosen action beat the BUY/SELL/HOLD alternatives
          </p>
        </div>
        <div className={card}>
          <div className={cn(label, 'mb-2')}>Drift</div>
          {snap.drift.alerts.length === 0 ? (
            <p className="text-sm text-emerald-500">No drift detected</p>
          ) : (
            <ul className="space-y-1 text-xs">
              {snap.drift.alerts.map((alert, i) => (
                <li key={i} className="text-amber-600 dark:text-amber-400">
                  {alert.metric} {alert.direction === 'down' ? '↓' : '↑'} {alert.recent} (was{' '}
                  {alert.baseline})
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

function AgentsPanel({ snap }: { snap: CognitiveSnapshot }) {
  const grades = new Map(snap.evolution.agent_grades.map((g) => [g.subject_id, g]))
  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
      {snap.agents_roster.map((agent) => {
        const signalName = agent.emits.replace('_signal', '')
        const grade = grades.get(signalName)
        const live = snap.live_agents[signalName as 'news' | 'tech' | 'macro' | 'risk'] ?? null
        return (
          <div key={agent.name} className={card}>
            <div className="flex items-center justify-between">
              <span className="font-medium text-slate-900 dark:text-slate-100">{agent.name}</span>
              {grade ? <Grade grade={grade.grade} /> : <span className={cn(chip, gradeTone(null))}>{agent.role}</span>}
            </div>
            <p className="mt-1 text-xs text-slate-500">{agent.description}</p>
            {grade && (
              <div className="mt-2 grid grid-cols-2 gap-1 text-xs text-slate-600 dark:text-slate-400">
                <span>score {grade.score}</span>
                <span>n {grade.samples ?? 0}</span>
                <span>hit {((grade.correct_rate ?? 0) * 100).toFixed(0)}%</span>
                <span>pnl {signed(grade.contribution ?? 0, 1)}</span>
              </div>
            )}
            {live && (
              <div className="mt-2 text-xs text-slate-400">
                last: {Object.entries(live)
                  .filter(([k]) => k !== 'type')
                  .map(([k, v]) => `${k} ${typeof v === 'number' ? v : String(v)}`)
                  .join(' · ')}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function ProposalsPanel({ snap }: { snap: CognitiveSnapshot }) {
  if (snap.proposals.length === 0) {
    return (
      <div className={cn(card, 'text-sm text-slate-400')}>
        No proposals yet — the ProposalAgent fires once an agent shows a statistically backed edge.
      </div>
    )
  }
  return (
    <div className="space-y-3">
      {snap.proposals.map((entry) => (
        <ProposalCard key={entry.proposal.proposal_id} entry={entry} />
      ))}
    </div>
  )
}

function ProposalCard({ entry }: { entry: QueueEntry }) {
  const { proposal, verdict, delta, status, proposal_grade, pull_request } = entry
  return (
    <div className={card}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-slate-400">{proposal.proposal_id}</span>
          <span className={cn(chip, 'border-slate-500/20 bg-slate-500/10 text-slate-500')}>
            {proposal.proposal_type}
          </span>
          <span className={cn(chip, statusTone(status))}>{status}</span>
        </div>
        {proposal_grade && <Grade grade={proposal_grade.grade} />}
      </div>

      <div className="mt-2 font-mono text-sm">
        <span className="text-slate-500">{proposal.target}: </span>
        <span className="text-rose-500">{String(proposal.old_value)}</span>
        <span className="text-slate-400"> → </span>
        <span className="text-emerald-500">{String(proposal.new_value)}</span>
      </div>
      <p className="mt-1 text-xs text-slate-500">{proposal.reason}</p>

      {delta && (
        <div className="mt-2 flex flex-wrap gap-2 text-xs">
          <span className="rounded bg-slate-100 px-2 py-0.5 dark:bg-slate-800">
            ΔPnL {signed(delta.pnl_delta)}%
          </span>
          <span className="rounded bg-slate-100 px-2 py-0.5 dark:bg-slate-800">
            ΔSharpe {signed(delta.sharpe_delta)}
          </span>
          <span className="rounded bg-slate-100 px-2 py-0.5 dark:bg-slate-800">
            ΔDrawdown {signed(delta.drawdown_delta)}%
          </span>
        </div>
      )}

      {verdict && (
        <div className="mt-2 text-xs">
          <span className={cn(chip, verdict.approved ? statusTone('approved') : statusTone('rejected'))}>
            challenger: {verdict.approved ? 'APPROVE' : 'REJECT'} · risk {verdict.risk_score}
          </span>
          <ul className="mt-1 list-disc pl-5 text-slate-500">
            {verdict.reasons.map((reason, i) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
      {pull_request && (
        <div className="mt-2 text-xs text-slate-400">PR branch: {pull_request.branch} (no auto-merge)</div>
      )}
    </div>
  )
}

function EvolutionPanel({ snap }: { snap: CognitiveSnapshot }) {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div className={card}>
        <div className={cn(label, 'mb-2')}>Config Evolution</div>
        <ol className="space-y-2">
          {snap.evolution.config_versions.map((cv) => (
            <li key={cv.version} className="flex items-center gap-2 text-sm">
              <span className="font-mono text-slate-500">v{cv.version}</span>
              {cv.grade ? <Grade grade={cv.grade.grade} /> : <span className="text-xs text-slate-400">active</span>}
              <span className="text-xs text-slate-400">
                news {cv.config.weights.news} · tech {cv.config.weights.tech} · macro{' '}
                {cv.config.weights.macro}
              </span>
            </li>
          ))}
        </ol>
      </div>
      <div className={card}>
        <div className={cn(label, 'mb-2')}>Proposal Success by Type</div>
        {Object.keys(snap.evolution.proposal_success_rates).length === 0 ? (
          <p className="text-xs text-slate-400">No proposals scored yet.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {Object.entries(snap.evolution.proposal_success_rates).map(([type, stat]) => (
              <li key={type} className="flex justify-between">
                <span className="text-slate-600 dark:text-slate-300">{type}</span>
                <span className="text-slate-500">
                  {(stat.success_rate * 100).toFixed(0)}% ({stat.successes}/{stat.attempts})
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function TracesPanel({ traces }: { traces: TradeTrace[] }) {
  const [open, setOpen] = useState<string | null>(traces[0]?.trace_id ?? null)
  if (traces.length === 0) {
    return <div className={cn(card, 'text-sm text-slate-400')}>No trades traced yet.</div>
  }
  return (
    <div className="space-y-2">
      {traces.map((trace) => {
        const isOpen = open === trace.trace_id
        const decision = trace.decision
        return (
          <div key={trace.trace_id} className={card}>
            <button
              onClick={() => setOpen(isOpen ? null : trace.trace_id)}
              className="flex w-full items-center justify-between text-left"
            >
              <span className="font-mono text-xs text-slate-500">{trace.trace_id}</span>
              <span className="flex items-center gap-2">
                {decision && (
                  <span className={cn(chip, actionTone(decision.action))}>
                    {decision.action.toUpperCase()}
                  </span>
                )}
                {trace.grade && <Grade grade={trace.grade.grade} />}
              </span>
            </button>
            {isOpen && (
              <div className="mt-3 space-y-2 border-t border-slate-100 pt-3 text-xs dark:border-slate-800">
                <Step name="Agent signals">
                  news {num(trace.signals.news, 'sentiment')} · tech {num(trace.signals.tech, 'trend')} ·
                  macro {num(trace.signals.macro, 'regime')} · risk {num(trace.signals.risk, 'risk_score')}
                </Step>
                <Step name="Reasoning">{str(trace.reasoning, 'summary') || '—'}</Step>
                <Step name="Decision">
                  {decision ? `${decision.action.toUpperCase()} @ score ${signed(decision.score, 3)}` : '—'}
                </Step>
                <Step name="Risk gate">
                  {trace.risk_gate
                    ? `${num(trace.risk_gate, 'allowed') ? 'allowed' : 'blocked'} ${
                        Array.isArray(trace.risk_gate.blocks)
                          ? (trace.risk_gate.blocks as string[]).join(', ')
                          : ''
                      }`
                    : '—'}
                </Step>
                <Step name="Execution">
                  {trace.execution
                    ? `${str(trace.execution, 'status')} ${num(trace.execution, 'qty')} @ ${num(
                        trace.execution,
                        'price',
                      )}`
                    : '—'}
                </Step>
                <Step name="Outcome">
                  {trace.outcome ? `${signed(num(trace.outcome, 'realized_pnl_pct'))}%` : '—'}
                </Step>
                {trace.counterfactual && (
                  <Step name="Counterfactual">
                    best {trace.counterfactual.best_action.toUpperCase()} · regret{' '}
                    {signed(trace.counterfactual.regret_pct)}% ·{' '}
                    {trace.counterfactual.was_best ? 'chose best' : 'suboptimal'}
                  </Step>
                )}
                {trace.grade && (
                  <Step name="Grade">
                    overall {trace.grade.grade} · dir {trace.grade.direction_grade} · risk{' '}
                    {trace.grade.risk_grade} · exec {trace.grade.execution_grade} · timing{' '}
                    {trace.grade.timing_grade}
                  </Step>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function Step({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <span className="w-28 shrink-0 text-slate-400">{name}</span>
      <span className="text-slate-700 dark:text-slate-300">{children}</span>
    </div>
  )
}

function EventsPanel({ events }: { events: CognitiveEvent[] }) {
  const recent = [...events].reverse()
  return (
    <div className={cn(card, 'max-h-[28rem] overflow-auto')}>
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-white text-slate-400 dark:bg-slate-900/40">
          <tr>
            <th className="py-1 pr-2">#</th>
            <th className="py-1 pr-2">type</th>
            <th className="py-1 pr-2">source</th>
            <th className="py-1">trace</th>
          </tr>
        </thead>
        <tbody>
          {recent.map((event) => (
            <tr key={event.seq} className="border-t border-slate-50 dark:border-slate-800/60">
              <td className="py-1 pr-2 font-mono text-slate-400">{event.seq}</td>
              <td className="py-1 pr-2 font-medium text-slate-700 dark:text-slate-300">
                {event.type}
              </td>
              <td className="py-1 pr-2 text-slate-500">{event.source || '—'}</td>
              <td className="py-1 font-mono text-slate-400">{event.trace_id || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
