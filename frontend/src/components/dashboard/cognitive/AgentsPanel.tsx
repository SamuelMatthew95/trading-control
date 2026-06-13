'use client'

import { cn } from '@/lib/utils'
import { FIELD_TYPE } from '@/lib/cognitive'
import { gradeTone } from '@/lib/grade-colors'
import type { CognitiveSnapshot } from '@/types/cognitive'

import { card, chip, COPY, Grade, healthChip } from './cognitive-ui'

export function AgentsPanel({ snap }: { snap: CognitiveSnapshot }) {
  const grades = new Map(snap.evolution.agent_grades.map((g) => [g.subject_id, g]))
  const agentsHealth = snap.health.agents
  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
      {snap.agents_roster.map((agent) => {
        // Live roster: grades / activity / health all key by the canonical
        // agent name (cognitive_live normalizes sources to these constants).
        const grade = grades.get(agent.name)
        const live = snap.live_agents[agent.name] ?? null
        const health = agentsHealth[agent.name]
        return (
          <div key={agent.name} className={card}>
            <div className="flex items-center justify-between">
              <span className="font-medium text-foreground">{agent.name}</span>
              {grade ? (
                <Grade grade={grade.grade} />
              ) : (
                <span className={cn(chip, gradeTone(null))}>{agent.role}</span>
              )}
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
                  .filter(([k, v]) => k !== FIELD_TYPE && v != null)
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
