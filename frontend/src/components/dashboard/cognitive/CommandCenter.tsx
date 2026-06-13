'use client'

import { cn } from '@/lib/utils'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { formatPercent } from '@/lib/formatters'
import { actionTone, summarizeDecisions } from '@/lib/cognitive'
import type { CognitiveSnapshot } from '@/types/cognitive'

import {
  card,
  chip,
  CMD,
  COPY,
  DecisionReasoningCard,
  healthChip,
  label,
} from './cognitive-ui'

export function CommandCenter({ snap }: { snap: CognitiveSnapshot }) {
  const { health, decision } = snap
  const stats = summarizeDecisions(decision.recent)
  const latest = decision.latest
  const llmTone =
    stats.successRate == null
      ? 'text-muted-foreground'
      : stats.fallbacks > 0
        ? 'text-warning'
        : 'text-success'

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className={card}>
          <div className={label}>{CMD.decisions}</div>
          <div className="mt-1 text-2xl font-semibold text-foreground">{stats.total}</div>
          <div className="mt-1 flex gap-2 font-mono text-xs tabular-nums">
            <span className="text-success">
              {stats.buys} {CMD.buysShort}
            </span>
            <span className="text-danger">
              {stats.sells} {CMD.sellsShort}
            </span>
            <span className="text-muted-foreground">
              {stats.holds} {CMD.holdsShort}
            </span>
          </div>
        </div>
        <div className={card}>
          <div className={label}>{CMD.llmReasoning}</div>
          <div className={cn('mt-1 text-2xl font-semibold', llmTone)}>
            {stats.successRate == null ? NO_DATA : formatPercent(stats.successRate, { decimals: 0 })}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {stats.successRate == null
              ? CMD.llmUnknown
              : stats.fallbacks > 0
                ? `${stats.fallbacks} ${CMD.fallbacks}`
                : CMD.llmAllReasoned}
          </div>
        </div>
        <div className={card}>
          <div className={label}>{CMD.latestDecision}</div>
          <div className="mt-1 flex items-center gap-2">
            <span className={cn(chip, actionTone(latest?.action))}>
              {(latest?.action || UI_COPY.terminal.defaultAction).toUpperCase()}
            </span>
            <span className="font-mono text-sm font-medium text-foreground/80">
              {latest?.symbol ?? NO_DATA}
            </span>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {CMD.avgConfidence} {formatPercent(stats.avgConfidence, { decimals: 0 })}
          </div>
        </div>
        <div className={card}>
          <div className={label}>{CMD.activeConfig}</div>
          <div className="mt-1 text-2xl font-semibold text-foreground">v{snap.config.version}</div>
          <div className="mt-1 text-xs text-muted-foreground">{CMD.configVersion}</div>
        </div>
      </div>

      {latest ? (
        <DecisionReasoningCard decision={latest} title={CMD.latestReasoning} />
      ) : (
        <div className={cn(card, 'text-sm text-muted-foreground')}>{CMD.noDecisions}</div>
      )}

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
    </div>
  )
}
