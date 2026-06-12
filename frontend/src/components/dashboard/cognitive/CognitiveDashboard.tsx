'use client'

import { Fragment, useCallback, useEffect, useState } from 'react'
import {
  Activity,
  Brain,
  GitPullRequest,
  History,
  Radio,
  Repeat,
  Workflow,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import { cardClass, chipClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { TONE_BADGE_OUTLINED } from '@/lib/design/sentiment'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { LoadingState } from '@/components/ui/loading'
import { PageHeader } from '@/components/ui/page-header'
import { PromptEvolutionPanel } from '@/components/dashboard/PromptEvolutionPanel'
import { ToolGovernancePanel } from '@/components/dashboard/ToolGovernancePanel'
import {
  actionTone,
  fetchCognitiveEvents,
  fetchCognitiveState,
  signed,
  statusTone,
} from '@/lib/cognitive'
import { gradeTone } from '@/lib/grade-colors'
import type {
  CognitiveEvent,
  CognitiveSnapshot,
  TradeTrace,
} from '@/types/cognitive'

const COPY = UI_COPY.cognitive

const num = (obj: Record<string, unknown> | null | undefined, key: string): number => {
  const value = obj?.[key]
  return typeof value === 'number' ? value : Number(value ?? 0)
}
const str = (obj: Record<string, unknown> | null | undefined, key: string): string => {
  const value = obj?.[key]
  return value == null ? '' : String(value)
}

const TABS = [
  { id: 'command', label: COPY.tabs.command, Icon: Activity },
  { id: 'loop', label: COPY.tabs.loop, Icon: Repeat },
  { id: 'agents', label: COPY.tabs.agents, Icon: Brain },
  { id: 'proposals', label: COPY.tabs.proposals, Icon: GitPullRequest },
  { id: 'evolution', label: COPY.tabs.evolution, Icon: History },
  { id: 'traces', label: COPY.tabs.traces, Icon: Workflow },
  { id: 'events', label: COPY.tabs.events, Icon: Radio },
] as const

// The self-evolving cognition loop, stage by stage (mirrors CLAUDE.md).
const LOOP_STAGES = COPY.loopStages

type TabId = (typeof TABS)[number]['id']

// Shared dual-theme surface recipes.
const card = cardClass
const chip = chipClass
const label = sectionTitleClass
const pageShell = 'min-h-screen bg-background px-3 py-4 text-foreground sm:px-4'
const subTableHeadClass = 'bg-muted/60 text-3xs uppercase tracking-caps text-muted-foreground'

/** Outlined chip for an agent health status (healthy → success, else neutral). */
const healthChip = (status: string): string =>
  status === 'healthy' ? TONE_BADGE_OUTLINED.success : TONE_BADGE_OUTLINED.neutral

function Grade({ grade }: { grade: string | null | undefined }) {
  return <span className={cn(chip, gradeTone(grade))}>{grade || UI_COPY.learning.notRated}</span>
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
      setError(err instanceof Error ? err.message : COPY.apiErrorFallback)
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 10000)
    return () => clearInterval(timer)
  }, [load])

  if (error && !snap) {
    return (
      <div className={pageShell}>
        <div className={cn(card, 'mx-auto max-w-screen-2xl text-sm text-danger')}>
          {COPY.apiError} {error}
        </div>
      </div>
    )
  }
  if (!snap) {
    return (
      <div className={pageShell}>
        <div className={cn(card, 'mx-auto max-w-screen-2xl animate-pulse')}>
          <LoadingState label={UI_COPY.loading.cognitive} />
        </div>
      </div>
    )
  }

  return (
    <div className={pageShell}>
      <div className="mx-auto max-w-screen-2xl space-y-3">
        <PageHeader
          eyebrow={COPY.eyebrow}
          title={COPY.title}
          description={`${COPY.subtitleLoop} v${snap.config.version} · ${snap.event_count} ${COPY.subtitleEvents}`}
          right={
            <span className="rounded-full border px-2 py-1 font-mono text-3xs uppercase tracking-caps text-muted-foreground">
              {COPY.headerChip}
            </span>
          }
        />
        <nav className="flex flex-wrap gap-1 rounded-xl border bg-card p-2 dark:bg-card/80">
          {TABS.map(({ id, label: tabLabel, Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              aria-pressed={tab === id}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition',
                tab === id
                  ? 'bg-foreground text-background'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground',
              )}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden />
              {tabLabel}
            </button>
          ))}
        </nav>

      {tab === 'command' && <CommandCenter snap={snap} />}
      {tab === 'loop' && <CognitionLoopPanel />}
      {tab === 'agents' && <AgentsPanel snap={snap} />}
      {tab === 'proposals' && <ProposalsPanel snap={snap} />}
      {tab === 'evolution' && <EvolutionPanel snap={snap} />}
      {tab === 'traces' && <TracesPanel traces={snap.traces} />}
      {tab === 'events' && <EventsPanel events={events} />}
      </div>
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
          <div className={label}>{COPY.system}</div>
          <div
            className={cn('mt-1 text-lg font-semibold', systemHealthy ? 'text-success' : 'text-warning')}
          >
            {systemHealthy ? COPY.healthy : COPY.warmingUp}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {learning.trades_graded}/{learning.trades_closed} {COPY.tradesGraded}
          </div>
        </div>
        <div className={card}>
          <div className={label}>{COPY.topDecision}</div>
          <div className="mt-1 flex items-center gap-2">
            <span className={cn(chip, actionTone(latest?.action))}>
              {(latest?.action || UI_COPY.terminal.defaultAction).toUpperCase()}
            </span>
            <span className="text-sm font-medium text-foreground/80">
              {latest ? signed(latest.score, 3) : NO_DATA}
            </span>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {COPY.band} [{decision.sell_threshold}, {decision.buy_threshold}]
          </div>
        </div>
        <div className={card}>
          <div className={label}>{COPY.activeConfig}</div>
          <div className="mt-1 text-lg font-semibold text-foreground">v{snap.config.version}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {pipeline.merged} {COPY.merged} · {pipeline.generated} {COPY.proposed}
          </div>
        </div>
        <div className={card}>
          <div className={label}>{COPY.proposalPipeline}</div>
          <div className="mt-1 text-sm text-foreground/80">
            {pipeline.approved} {COPY.approved} · {pipeline.rejected} {COPY.rejected}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {pipeline.backtested} {COPY.backtested}
          </div>
        </div>
      </div>

      <div className={card}>
        <div className={cn(label, 'mb-2')}>{COPY.agentHealth}</div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(health.agents).map(([name, info]) => (
            <span key={name} className={cn(chip, healthChip(info.status))}>
              {name} · {info.events}
            </span>
          ))}
        </div>
      </div>

      {latest && (
        <div className={card}>
          <div className={cn(label, 'mb-2')}>{COPY.decisionFlow}</div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {Object.entries(latest.breakdown).map(([sig, contrib]) => (
              <span key={sig} className="rounded-md bg-muted px-2 py-1 text-foreground/80">
                {sig} {signed(contrib, 3)}
              </span>
            ))}
            <span className="text-muted-foreground/70">→</span>
            <span className="font-semibold">{signed(latest.score, 3)}</span>
            <span className="text-muted-foreground/70">→</span>
            <span className={cn(chip, actionTone(latest.action))}>{latest.action.toUpperCase()}</span>
          </div>
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        <div className={card}>
          <div className={cn(label, 'mb-2')}>{COPY.decisionQuality}</div>
          <div className="flex gap-4 text-sm text-foreground/80">
            <span>
              {COPY.bestActionRate} <b>{((snap.learning.best_action_rate ?? 0) * 100).toFixed(0)}%</b>
            </span>
            <span>
              {COPY.meanRegret} <b>{signed(snap.learning.mean_regret_pct ?? 0)}%</b>
            </span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{COPY.qualityNote}</p>
        </div>
        <div className={card}>
          <div className={cn(label, 'mb-2')}>{COPY.drift}</div>
          {snap.drift.alerts.length === 0 ? (
            <p className="text-sm text-success">{COPY.noDrift}</p>
          ) : (
            <ul className="space-y-1 text-xs">
              {snap.drift.alerts.map((alert, i) => (
                <li key={i} className="text-warning">
                  {alert.metric} {alert.direction === 'down' ? '↓' : '↑'} {alert.recent} ({COPY.was}{' '}
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

function CognitionLoopPanel() {
  return (
    <div className="space-y-4">
      <div className={card}>
        <div className={cn(label, 'mb-3')}>{COPY.loopTitle}</div>
        <div className="flex flex-wrap items-center gap-2">
          {LOOP_STAGES.map((stage, i) => (
            <Fragment key={stage.label}>
              <div className="rounded-lg border px-3 py-1.5">
                <div className="text-sm font-medium text-foreground">{stage.label}</div>
                <div className="text-2xs text-muted-foreground">{stage.note}</div>
              </div>
              {i < LOOP_STAGES.length - 1 && <span className="text-muted-foreground/70">→</span>}
            </Fragment>
          ))}
          <span className="ml-1 inline-flex items-center gap-1 rounded-md bg-brand/15 px-2 py-1 text-2xs font-semibold text-brand">
            <Repeat className="h-3 w-3" aria-hidden /> {COPY.directiveEvolves}
          </span>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">{COPY.loopDescription}</p>
      </div>
      <div className="grid gap-3 lg:grid-cols-2 lg:items-start">
        <PromptEvolutionPanel />
        <ToolGovernancePanel />
      </div>
    </div>
  )
}

function AgentsPanel({ snap }: { snap: CognitiveSnapshot }) {
  const grades = new Map(snap.evolution.agent_grades.map((g) => [g.subject_id, g]))
  const agentsHealth = snap.health.agents
  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
      {snap.agents_roster.map((agent) => {
        // Real roster: key by agent name first; fall back to the sim's
        // emits-derived key so the seeded demo still attaches.
        const signalName = agent.emits.replace('_signal', '')
        const grade = grades.get(agent.name) ?? grades.get(signalName)
        const live = snap.live_agents[agent.name] ?? snap.live_agents[signalName] ?? null
        const health = agentsHealth[agent.name]
        return (
          <div key={agent.name} className={card}>
            <div className="flex items-center justify-between">
              <span className="font-medium text-foreground">{agent.name}</span>
              {grade ? <Grade grade={grade.grade} /> : <span className={cn(chip, gradeTone(null))}>{agent.role}</span>}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{agent.description}</p>
            {health && (
              <div className="mt-2 flex items-center gap-2 text-xs">
                <span className={cn(chip, healthChip(health.status))}>{health.status}</span>
                <span className="text-muted-foreground">
                  {health.events} {COPY.events}
                </span>
              </div>
            )}
            {grade && (
              <div className="mt-2 grid grid-cols-2 gap-1 text-xs text-foreground/70">
                <span>
                  {COPY.score} {grade.score}
                </span>
                <span>
                  {COPY.samples} {grade.samples ?? 0}
                </span>
              </div>
            )}
            {live && (
              <div className="mt-2 text-xs text-muted-foreground">
                {COPY.lastPrefix}{' '}
                {Object.entries(live)
                  .filter(([k, v]) => k !== 'type' && v != null)
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
    return <div className={cn(card, 'text-sm text-muted-foreground')}>{COPY.proposalsEmpty}</div>
  }
  return (
    <div className={cn(card, 'overflow-x-auto p-0')}>
      <table className="w-full min-w-[840px] text-left text-xs">
        <thead className={subTableHeadClass}>
          <tr>
            <th className="px-3 py-2 font-semibold">{COPY.columns.proposal}</th>
            <th className="px-3 py-2 font-semibold">{COPY.columns.change}</th>
            <th className="px-3 py-2 font-semibold">{COPY.columns.backtestDelta}</th>
            <th className="px-3 py-2 font-semibold">{COPY.columns.verdict}</th>
            <th className="px-3 py-2 font-semibold">{COPY.columns.status}</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {snap.proposals.map((entry) => {
            const { proposal, verdict, delta, status, proposal_grade } = entry
            return (
              <tr key={proposal.proposal_id} className="align-top text-foreground/70">
                <td className="px-3 py-2">
                  <p className="font-mono text-2xs text-muted-foreground">{proposal.proposal_id}</p>
                  <p className="mt-1 text-muted-foreground">{proposal.proposal_type}</p>
                </td>
                <td className="px-3 py-2">
                  <p className="font-mono text-sm">
                    <span className="text-muted-foreground">{proposal.target}: </span>
                    <span className="text-danger">{String(proposal.old_value)}</span>
                    <span className="text-muted-foreground"> → </span>
                    <span className="text-success">{String(proposal.new_value)}</span>
                  </p>
                  <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{proposal.reason}</p>
                </td>
                <td className="px-3 py-2 font-mono text-2xs text-muted-foreground">
                  {delta ? (
                    <span>
                      {COPY.deltaPnl} {signed(delta.pnl_delta)}% · {COPY.deltaSharpe}{' '}
                      {signed(delta.sharpe_delta)} · {COPY.deltaDrawdown} {signed(delta.drawdown_delta)}%
                    </span>
                  ) : (
                    NO_DATA
                  )}
                </td>
                <td className="px-3 py-2">
                  {verdict ? (
                    <div className="space-y-1">
                      <span className={cn(chip, verdict.approved ? statusTone('approved') : statusTone('rejected'))}>
                        {verdict.approved ? COPY.verdictApprove : COPY.verdictReject} · {COPY.risk}{' '}
                        {verdict.risk_score}
                      </span>
                      <p className="line-clamp-2 text-muted-foreground">{verdict.reasons.join(' · ')}</p>
                    </div>
                  ) : (
                    <span className="text-muted-foreground">{COPY.pendingReview}</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    <span className={cn(chip, statusTone(status))}>{status}</span>
                    {proposal_grade && <Grade grade={proposal_grade.grade} />}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function EvolutionPanel({ snap }: { snap: CognitiveSnapshot }) {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div className={card}>
        <div className={cn(label, 'mb-2')}>{COPY.configEvolution}</div>
        {snap.evolution.config_versions.length === 0 ? (
          <p className="text-xs text-muted-foreground">{COPY.configEvolutionEmpty}</p>
        ) : (
          <ol className="space-y-2">
            {snap.evolution.config_versions.map((cv) => (
              <li key={cv.version} className="flex items-start gap-2 text-sm">
                <span className="font-mono text-muted-foreground">v{cv.version}</span>
                {cv.grade ? (
                  <Grade grade={cv.grade.grade} />
                ) : (
                  <span className="text-xs text-muted-foreground">{COPY.active}</span>
                )}
                <span className="line-clamp-2 text-xs text-muted-foreground">
                  {cv.config.rationale && cv.config.rationale.length > 0
                    ? cv.config.rationale
                    : COPY.directivePromoted}
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
      <div className={card}>
        <div className={cn(label, 'mb-2')}>{COPY.successByType}</div>
        {Object.keys(snap.evolution.proposal_success_rates).length === 0 ? (
          <p className="text-xs text-muted-foreground">{COPY.noProposalsScored}</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {Object.entries(snap.evolution.proposal_success_rates).map(([type, stat]) => (
              <li key={type} className="flex justify-between">
                <span className="text-foreground/70">{type}</span>
                <span className="text-muted-foreground">
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
    return <div className={cn(card, 'text-sm text-muted-foreground')}>{COPY.noTraces}</div>
  }
  return (
    <div className="space-y-2">
      {traces.map((trace) => {
        const isOpen = open === trace.trace_id
        const decision = trace.decision
        return (
          <div key={trace.trace_id} className={card}>
            <button
              type="button"
              onClick={() => setOpen(isOpen ? null : trace.trace_id)}
              aria-expanded={isOpen}
              className="flex w-full items-center justify-between text-left"
            >
              <span className="font-mono text-xs text-muted-foreground">{trace.trace_id}</span>
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
              <div className="mt-3 space-y-2 border-t pt-3 text-xs">
                <Step name={COPY.steps.signals}>
                  news {num(trace.signals.news, 'sentiment')} · tech {num(trace.signals.tech, 'trend')} ·
                  macro {num(trace.signals.macro, 'regime')} · risk {num(trace.signals.risk, 'risk_score')}
                </Step>
                <Step name={COPY.steps.reasoning}>{str(trace.reasoning, 'summary') || NO_DATA}</Step>
                <Step name={COPY.steps.decision}>
                  {decision
                    ? `${decision.action.toUpperCase()} ${COPY.atScore} ${signed(decision.score, 3)}`
                    : NO_DATA}
                </Step>
                <Step name={COPY.steps.riskGate}>
                  {trace.risk_gate
                    ? `${num(trace.risk_gate, 'allowed') ? COPY.allowed : COPY.blocked} ${
                        Array.isArray(trace.risk_gate.blocks)
                          ? (trace.risk_gate.blocks as string[]).join(', ')
                          : ''
                      }`
                    : NO_DATA}
                </Step>
                <Step name={COPY.steps.execution}>
                  {trace.execution
                    ? `${str(trace.execution, 'status')} ${num(trace.execution, 'qty')} @ ${num(
                        trace.execution,
                        'price',
                      )}`
                    : NO_DATA}
                </Step>
                <Step name={COPY.steps.outcome}>
                  {trace.outcome ? `${signed(num(trace.outcome, 'realized_pnl_pct'))}%` : NO_DATA}
                </Step>
                {trace.counterfactual && (
                  <Step name={COPY.steps.counterfactual}>
                    {COPY.best} {trace.counterfactual.best_action.toUpperCase()} · {COPY.regret}{' '}
                    {signed(trace.counterfactual.regret_pct)}% ·{' '}
                    {trace.counterfactual.was_best ? COPY.choseBest : COPY.suboptimal}
                  </Step>
                )}
                {trace.grade && (
                  <Step name={COPY.steps.grade}>
                    {COPY.gradeOverall} {trace.grade.grade} · {COPY.gradeDirection}{' '}
                    {trace.grade.direction_grade} · {COPY.gradeRisk} {trace.grade.risk_grade} ·{' '}
                    {COPY.gradeExecution} {trace.grade.execution_grade} · {COPY.gradeTiming}{' '}
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
      <span className="w-28 shrink-0 text-muted-foreground">{name}</span>
      <span className="text-foreground/80">{children}</span>
    </div>
  )
}

function EventsPanel({ events }: { events: CognitiveEvent[] }) {
  const recent = [...events].reverse()
  return (
    <div className={cn(card, 'max-h-[28rem] overflow-auto')}>
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 z-sticky bg-card text-muted-foreground dark:bg-popover">
          <tr>
            <th className="py-1 pr-2">{COPY.eventColumns.seq}</th>
            <th className="py-1 pr-2">{COPY.eventColumns.type}</th>
            <th className="py-1 pr-2">{COPY.eventColumns.source}</th>
            <th className="py-1">{COPY.eventColumns.trace}</th>
          </tr>
        </thead>
        <tbody>
          {recent.map((event) => (
            <tr key={event.seq} className="border-t">
              <td className="py-1 pr-2 font-mono text-muted-foreground">{event.seq}</td>
              <td className="py-1 pr-2 font-medium text-foreground/80">{event.type}</td>
              <td className="py-1 pr-2 text-muted-foreground">{event.source || NO_DATA}</td>
              <td className="py-1 font-mono text-muted-foreground">{event.trace_id || NO_DATA}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
