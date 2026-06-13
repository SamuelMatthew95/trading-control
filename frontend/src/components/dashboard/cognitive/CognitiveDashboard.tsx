'use client'

import { useCallback, useEffect, useState } from 'react'
import { Activity, Brain, GitPullRequest, History, Radio, Repeat, Workflow } from 'lucide-react'

import { cn } from '@/lib/utils'
import { UI_COPY } from '@/constants/copy'
import { LoadingState } from '@/components/ui/loading'
import { PageHeader } from '@/components/ui/page-header'
import { fetchCognitiveEvents, fetchCognitiveState } from '@/lib/cognitive'
import type { CognitiveEvent, CognitiveSnapshot } from '@/types/cognitive'

import { card, COPY, pageShell } from './cognitive-ui'
import { CommandCenter } from './CommandCenter'
import { CognitionLoopPanel } from './CognitionLoopPanel'
import { AgentsPanel } from './AgentsPanel'
import { ProposalsPanel } from './ProposalsPanel'
import { EvolutionPanel } from './EvolutionPanel'
import { TracesPanel } from './TracesPanel'
import { EventsPanel } from './EventsPanel'

const TABS = [
  { id: 'command', label: COPY.tabs.command, Icon: Activity },
  { id: 'loop', label: COPY.tabs.loop, Icon: Repeat },
  { id: 'agents', label: COPY.tabs.agents, Icon: Brain },
  { id: 'proposals', label: COPY.tabs.proposals, Icon: GitPullRequest },
  { id: 'evolution', label: COPY.tabs.evolution, Icon: History },
  { id: 'traces', label: COPY.tabs.traces, Icon: Workflow },
  { id: 'events', label: COPY.tabs.events, Icon: Radio },
] as const

type TabId = (typeof TABS)[number]['id']

const POLL_INTERVAL_MS = 10000
const EVENT_LIMIT = 200

export function CognitiveDashboard() {
  const [tab, setTab] = useState<TabId>('command')
  const [snap, setSnap] = useState<CognitiveSnapshot | null>(null)
  const [events, setEvents] = useState<CognitiveEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [state, ev] = await Promise.all([
        fetchCognitiveState(),
        fetchCognitiveEvents(EVENT_LIMIT),
      ])
      setSnap(state)
      setEvents(ev)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : COPY.apiErrorFallback)
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, POLL_INTERVAL_MS)
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
