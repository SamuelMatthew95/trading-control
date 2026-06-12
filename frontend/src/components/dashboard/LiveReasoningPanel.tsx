'use client'

import { useState } from 'react'

import { API_ENDPOINTS } from '@/lib/apiClient'
import { usePolledApi } from '@/hooks/usePolledApi'
import { LEARNING_REFRESH_MS } from '@/lib/grade-colors'
import { cardClass, errorTextClass, mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'
import {
  sentimentTextClass,
  TONE_BADGE_OUTLINED,
  TONE_DOT,
  TONE_TEXT,
  type Tone,
} from '@/lib/design/sentiment'
import { proposalStatusTone } from '@/lib/dashboard-helpers'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Meter } from '@/components/ui/meter'
import { cn } from '@/lib/utils'

// Mirrors api/services/dashboard/prompt_os.py response models.
interface ToolView {
  name: string
  phase: string
  enabled: boolean
  alpha_score: number
  latency_ms: number
  failure_rate: number
  call_count: number
}
interface LiveView {
  node: string
  strategy_version: number | null
  config: Record<string, unknown>
  active_tools: ToolView[]
  assembled_prompt: string
  constitution: string
  output_contract: string
}
interface ChallengerView {
  challenger_id: string
  fills: number
  max_fills: number
  running: boolean
  variant: string | null
  tool_overrides: string[] | null
  config_diff: Record<string, unknown>
  differs_by: string
}
interface ProposalView {
  id: string
  proposal_type: string
  description: string
  confidence: number | null
  status: string
  applied: boolean
}
interface LiveReasoningResponse {
  champion: LiveView
  challengers: ChallengerView[]
  proposals: ProposalView[]
  tool_count: number
  timestamp: string
}

type LlmStatus = 'live' | 'degraded' | 'down' | 'unknown'

function coerceLlmStatus(value: unknown): LlmStatus {
  return value === 'live' || value === 'degraded' || value === 'down' ? value : 'unknown'
}

// Header indicator per LLM status. When the provider is degraded/down the live
// strategy below is still the configured one, but decisions are rule-based
// fallbacks — so the dot must stop claiming a healthy green "live".
const LLM_INDICATOR: Record<LlmStatus, { label: string; tone: Tone; pulse: boolean }> = {
  live: { label: UI_COPY.liveReasoning.llmLive, tone: 'success', pulse: true },
  degraded: { label: UI_COPY.liveReasoning.llmDegraded, tone: 'warning', pulse: false },
  down: { label: UI_COPY.liveReasoning.llmDown, tone: 'danger', pulse: false },
  unknown: { label: UI_COPY.liveReasoning.llmUnknown, tone: 'neutral', pulse: false },
}

function ToolChip({ tool }: { tool: ToolView }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border bg-muted/40 px-2 py-1"
      title={`${tool.phase} · α ${tool.alpha_score.toFixed(2)} · ${tool.latency_ms.toFixed(0)}ms · ${tool.call_count} calls`}
    >
      <span className="font-mono text-2xs text-foreground/80">{tool.name}</span>
      <span className={cn('font-mono text-3xs tabular-nums', sentimentTextClass(tool.alpha_score))}>
        α{tool.alpha_score >= 0 ? '+' : ''}
        {tool.alpha_score.toFixed(2)}
      </span>
      {tool.call_count > 0 && (
        <span className="font-mono text-3xs tabular-nums text-muted-foreground/70">
          ×{tool.call_count}
        </span>
      )}
    </span>
  )
}

function diffEntries(obj: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(obj).map(([k, v]) => [
    k,
    typeof v === 'object' ? JSON.stringify(v) : String(v),
  ])
}

/**
 * A challenger row that is not running, has zero fills, and carries no
 * configured difference is registry scaffolding — rendering its grid of
 * zeros/dashes reads as broken data. Only meaningful challengers get a card;
 * otherwise the section collapses to one explanatory empty state.
 */
function isMeaningfulChallenger(ch: ChallengerView): boolean {
  return (
    ch.running ||
    (ch.fills ?? 0) > 0 ||
    Boolean(ch.variant) ||
    (ch.tool_overrides?.length ?? 0) > 0 ||
    Object.keys(ch.config_diff ?? {}).length > 0
  )
}

function ChallengerCard({ ch }: { ch: ChallengerView }) {
  const pct = ch.max_fills > 0 ? Math.min(100, Math.round((ch.fills / ch.max_fills) * 100)) : 0
  const diffs = diffEntries(ch.config_diff)
  return (
    <div className="rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={cn('h-2 w-2 rounded-full', ch.running ? TONE_DOT.success : TONE_DOT.neutral)} />
          <span className="font-mono text-xs text-foreground/80">
            challenger {ch.challenger_id}
          </span>
        </div>
        <span
          title={UI_COPY.liveReasoning.differsByTitle}
          className="rounded bg-brand/15 px-2 py-0.5 text-3xs font-semibold uppercase tracking-caps text-brand"
        >
          {UI_COPY.liveReasoning.differsBy} {ch.differs_by}
        </span>
      </div>

      <div className="mt-2">
        <div className="flex items-center justify-between text-2xs text-muted-foreground">
          <span title={UI_COPY.liveReasoning.shadowFillsTitle}>
            {UI_COPY.liveReasoning.shadowFills}
          </span>
          <span className="font-mono tabular-nums">
            {ch.fills}/{ch.max_fills}
          </span>
        </div>
        <Meter value={pct} label={UI_COPY.liveReasoning.shadowFills} className="mt-1" />
      </div>

      {ch.variant && (
        <p className={cn('mt-2 rounded border px-2 py-1 text-2xs', TONE_BADGE_OUTLINED.warning)}>
          {UI_COPY.liveReasoning.promptVariant} {ch.variant}
        </p>
      )}
      {ch.tool_overrides && ch.tool_overrides.length > 0 && (
        <p className="mt-2 font-mono text-2xs text-muted-foreground">
          {UI_COPY.liveReasoning.toolSet} {ch.tool_overrides.join(', ')}
        </p>
      )}
      {diffs.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {diffs.map(([k, v]) => (
            <Badge key={k} tone="neutral" size="xs" className="font-mono">
              {k}={v}
            </Badge>
          ))}
        </div>
      ) : (
        !ch.variant && (
          <p className="mt-2 text-2xs text-muted-foreground/70">{UI_COPY.liveReasoning.sameAsLive}</p>
        )
      )}
    </div>
  )
}

function ProposalRow({ p }: { p: ProposalView }) {
  return (
    <div className="rounded-lg border p-2.5">
      <div className="flex items-center justify-between gap-2">
        <Badge tone="neutral" size="xs" className="uppercase tracking-caps">
          {p.proposal_type.replace(/_/g, ' ')}
        </Badge>
        <div className="flex items-center gap-1.5">
          {p.applied && (
            <span className="rounded bg-brand/15 px-1.5 py-0.5 text-3xs font-semibold text-brand">
              {UI_COPY.liveReasoning.applied}
            </span>
          )}
          <Badge tone={proposalStatusTone(p.status)} size="xs">
            {p.status}
          </Badge>
        </div>
      </div>
      <p className="mt-1 line-clamp-2 text-xs leading-snug text-foreground/80">
        {p.description || NO_DATA}
      </p>
      {p.confidence != null && (
        <p className="mt-0.5 font-mono text-3xs text-muted-foreground/70">
          {UI_COPY.liveReasoning.confidence} {(p.confidence * 100).toFixed(0)}%
        </p>
      )}
    </div>
  )
}

export function LiveReasoningPanel() {
  const { data, error } = usePolledApi<LiveReasoningResponse>(
    API_ENDPOINTS.DASHBOARD_PROMPT_OS,
    LEARNING_REFRESH_MS,
  )
  // LLM health is best-effort: it drives the live/degraded indicator, but a
  // failure here must not blank the reasoning cockpit — usePolledApi keeps the
  // last good payload through transient failures.
  const { data: health } = usePolledApi<{ status?: string }>(
    API_ENDPOINTS.LLM_HEALTH,
    LEARNING_REFRESH_MS,
  )
  const llmStatus = coerceLlmStatus(health?.status)
  const [showPrompt, setShowPrompt] = useState(false)

  const live = data?.champion
  // Drop placeholder rows (no liveness, no fills, no diff) so the section never
  // renders a grid of meaningless zeros — see isMeaningfulChallenger.
  const challengers = (data?.challengers ?? []).filter(isMeaningfulChallenger)
  const proposals = data?.proposals ?? []
  const versionLabel = live?.strategy_version != null ? `v${live.strategy_version}` : 'default'
  const indicator = LLM_INDICATOR[llmStatus]
  const llmDegraded = llmStatus === 'down' || llmStatus === 'degraded'

  return (
    <div className={cardClass}>
      <div className="mb-1 flex items-center justify-between">
        <p className={sectionTitleClass}>{UI_COPY.liveReasoning.title}</p>
        {error ? (
          <span className={errorTextClass}>err: {error}</span>
        ) : (
          <span className={cn('flex items-center gap-1.5 font-mono text-xs', TONE_TEXT[indicator.tone])}>
            <span className="relative flex h-2 w-2">
              {indicator.pulse && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-60" />
              )}
              <span className={cn('relative inline-flex h-2 w-2 rounded-full', TONE_DOT[indicator.tone])} />
            </span>
            {indicator.label}
          </span>
        )}
      </div>
      <p className={cn(mutedClass, 'mb-3')}>{UI_COPY.liveReasoning.description}</p>

      {llmDegraded && (
        <div className={cn('mb-3 rounded-lg border px-3 py-2 text-2xs leading-snug', TONE_BADGE_OUTLINED.warning)}>
          LLM provider is{' '}
          {llmStatus === 'down'
            ? UI_COPY.liveReasoning.degradedBannerDown
            : UI_COPY.liveReasoning.degradedBannerDegraded}{' '}
          right now — live decisions are <strong>rule-based fallbacks</strong>, not model
          reasoning. The prompt and tools below are still the configured strategy.
        </div>
      )}

      {/* ── Live strategy: the prompt + active tools ───────────────────────── */}
      <div className="rounded-lg border bg-muted/30 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Badge tone="success" size="xs" className="uppercase tracking-caps font-bold">
              {UI_COPY.liveReasoning.liveBadge}
            </Badge>
            <span className="font-mono text-xs text-foreground/70">
              node={live?.node ?? 'reasoning'} · strategy={versionLabel}
            </span>
          </div>
          <Button variant="outline" size="xs" onClick={() => setShowPrompt((s) => !s)}>
            {showPrompt ? UI_COPY.liveReasoning.hidePrompt : UI_COPY.liveReasoning.viewPrompt}
          </Button>
        </div>

        <p className={cn(sectionTitleClass, 'mt-2')}>
          {UI_COPY.liveReasoning.toolsHeading} ({live?.active_tools.length ?? 0})
        </p>
        {live && live.active_tools.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {live.active_tools.map((t) => (
              <ToolChip key={t.name} tool={t} />
            ))}
          </div>
        ) : (
          <p className="mt-1 text-2xs text-muted-foreground/70">{UI_COPY.liveReasoning.noTools}</p>
        )}

        {showPrompt && live && (
          <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-foreground/90 p-3 text-2xs leading-relaxed text-background dark:bg-black/40 dark:text-foreground">
            {live.assembled_prompt}
          </pre>
        )}
      </div>

      {/* ── Challengers being tested + proposed changes ────────────────────── */}
      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div>
          <p className={cn(sectionTitleClass, 'mb-1.5')}>{UI_COPY.liveReasoning.challengersHeading}</p>
          {challengers.length === 0 ? (
            <EmptyState message={UI_COPY.liveReasoning.challengersEmpty} className="min-h-0 py-6" />
          ) : (
            <div className="space-y-2">
              {challengers.map((ch) => (
                <ChallengerCard key={ch.challenger_id} ch={ch} />
              ))}
            </div>
          )}
        </div>

        <div>
          <p className={cn(sectionTitleClass, 'mb-1.5')}>{UI_COPY.liveReasoning.proposalsHeading}</p>
          {proposals.length === 0 ? (
            <EmptyState message={UI_COPY.liveReasoning.proposalsEmpty} className="min-h-0 py-6" />
          ) : (
            <div className="space-y-2">
              {proposals.map((p) => (
                <ProposalRow key={p.id} p={p} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
