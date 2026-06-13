'use client'

import { cn } from '@/lib/utils'
import { formatPercent } from '@/lib/formatters'
import type { CognitiveSnapshot } from '@/types/cognitive'

import { card, COPY, Grade, label } from './cognitive-ui'

export function EvolutionPanel({ snap }: { snap: CognitiveSnapshot }) {
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
                  {formatPercent(stat.success_rate, { decimals: 0 })} ({stat.successes}/
                  {stat.attempts})
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
