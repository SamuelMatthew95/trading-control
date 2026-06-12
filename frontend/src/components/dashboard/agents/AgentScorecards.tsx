'use client'

import { useState } from 'react'

import { API_ENDPOINTS, api } from '@/lib/apiClient'
import { usePolledApi } from '@/hooks/usePolledApi'
import { LEARNING_REFRESH_MS, gradeBg, tierBadge, tierLabel } from '@/lib/grade-colors'
import { cardClass, errorTextClass, mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { agentDisplayName } from '@/constants/agents'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type {
  AgentPerformanceResponse,
  AgentScore,
  PromotionApplyResult,
} from '@/lib/agent-performance'
import { AgentDetailModal } from './AgentDetailModal'

function ScoreCard({ agent, onSelect }: { agent: AgentScore; onSelect: (name: string) => void }) {
  const exercised = agent.dimensions.filter((d) => d.data_available).length
  return (
    <button
      type="button"
      onClick={() => onSelect(agent.name)}
      className="flex flex-col gap-2 rounded-lg border p-3 text-left transition-colors hover:border-strong hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 truncate text-sm font-sans text-foreground">
          {agentDisplayName(agent.name)}
        </span>
        <span className={cn('shrink-0 rounded-md border px-1.5 py-0.5 text-xs font-bold', gradeBg(agent.grade))}>
          {agent.grade ?? NO_DATA}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span
          className={cn(
            'rounded border px-1.5 py-0.5 text-3xs font-semibold uppercase tracking-caps',
            tierBadge(agent.tier),
          )}
        >
          {agent.promoted && <span className="mr-0.5">★</span>}
          {tierLabel(agent.tier)}
        </span>
        <span className="font-mono text-2xs tabular-nums text-muted-foreground">
          {agent.score_pct == null ? UI_COPY.agentsPage.unrated : `${agent.score_pct}%`}
        </span>
      </div>
      <p className={cn(mutedClass, 'text-3xs')}>
        {agent.event_count.toLocaleString()} events · {exercised}/{agent.dimensions.length} dims scored
        {(agent.grade_streak ?? 0) > 0 && ` · streak ${agent.grade_streak}`}
      </p>
    </button>
  )
}

export function AgentScorecards() {
  const { data, error } = usePolledApi<AgentPerformanceResponse>(
    API_ENDPOINTS.AGENTS_PERFORMANCE,
    LEARNING_REFRESH_MS,
  )
  const [selected, setSelected] = useState<string | null>(null)
  const [applying, setApplying] = useState(false)
  const [applyMsg, setApplyMsg] = useState<string | null>(null)

  const applyPromotions = async () => {
    setApplying(true)
    setApplyMsg(null)
    try {
      const res = await fetch(api(API_ENDPOINTS.AGENTS_PROMOTION_APPLY), { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = (await res.json()) as PromotionApplyResult
      const n = json.applied.length
      setApplyMsg(
        json.enabled
          ? `Applied trust weights to ${n} agents (live)`
          : `Applied to ${n} agents — inert until trust weighting is enabled`,
      )
    } catch {
      setApplyMsg(UI_COPY.agentsPage.applyFailed)
    } finally {
      setApplying(false)
    }
  }

  const agents = data?.agents ?? []
  const promoted = data?.promoted ?? 0

  return (
    <div className={cardClass}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <p className={sectionTitleClass}>{UI_COPY.panels.agentScorecards}</p>
        <div className="flex items-center gap-2">
          {error ? (
            <span className={errorTextClass}>err: {error}</span>
          ) : (
            <span
              className="font-mono text-xs text-muted-foreground/70"
              title={UI_COPY.agentsPage.promotedTitle}
            >
              {promoted} {UI_COPY.agentsPage.promoted}
            </span>
          )}
          <Button
            onClick={applyPromotions}
            disabled={applying}
            title={UI_COPY.agentsPage.applyTitle}
          >
            {applying ? UI_COPY.agentsPage.applying : UI_COPY.actions.applyPromotions}
          </Button>
        </div>
      </div>
      {applyMsg && <p className={cn(mutedClass, 'mb-1')}>{applyMsg}</p>}
      <p className={cn(mutedClass, 'mb-3')}>{UI_COPY.agentsPage.scorecardsDescription}</p>

      {agents.length === 0 ? (
        <p className={cn(mutedClass)}>{UI_COPY.agentsPage.noTelemetry}</p>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4">
          {agents.map((agent) => (
            <ScoreCard key={agent.name} agent={agent} onSelect={setSelected} />
          ))}
        </div>
      )}

      {selected && <AgentDetailModal name={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
