'use client'

import { API_ENDPOINTS } from '@/lib/apiClient'
import { usePolledApi } from '@/hooks/usePolledApi'
import { LEARNING_REFRESH_MS } from '@/lib/grade-colors'
import { cardClass, errorTextClass, mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { sentimentTextClass, TONE_BADGE, TONE_DOT, type Tone } from '@/lib/design/sentiment'
import { UI_COPY } from '@/constants/copy'
import { cn } from '@/lib/utils'

// Mirrors api.services.tool_registry.ToolMetadata serialization.
interface Tool {
  name: string
  phase: string
  description: string
  enabled: boolean
  alpha_score: number
  latency_ms: number
  failure_rate: number
  call_count: number
  success_count: number
  required_state_flags: string[]
  unlocks: string[]
}

// Mirrors api.services.tool_registry.ToolSuggestion serialization.
interface Suggestion {
  tool: string
  action: string
  severity: string
  reason: string
}

interface ToolRegistryResponse {
  tools: Tool[]
  capability_graph: Record<string, string[]>
  suggestions: Suggestion[]
  count: number
}

const COPY = UI_COPY.toolGovernance

// DAG phase order — perception → memory → risk → execution → optimization.
const PHASE_ORDER = ['perception', 'memory', 'risk', 'execution', 'optimization'] as const

// The reasoning LLM only ever gathers perception + memory tools. Risk/execution/
// optimization tools live on downstream nodes, so they read as "unused" here by
// design — not because they are broken.
const REASONING_PHASES = new Set(['perception', 'memory'])

const TOOL_COLUMNS = [
  COPY.columns.tool,
  COPY.columns.status,
  COPY.columns.calls,
  COPY.columns.alpha,
  COPY.columns.latency,
  COPY.columns.err,
] as const

// Plain-English WHY a tool has never been called, so "unused" is never a mystery.
function unusedReason(tool: Tool): string {
  if (!REASONING_PHASES.has(tool.phase)) {
    return COPY.unusedDownstream
  }
  if (tool.required_state_flags.length > 0) {
    return `${COPY.unusedGatedPrefix} ${tool.required_state_flags.join(', ')} ${COPY.unusedGatedSuffix}`
  }
  return COPY.unusedEligible
}

// Governance actions are a vocabulary of their own (disable/prioritize/review),
// resolved to Tones here — distinct from the BUY/SELL actionBadgeClass.
const GOVERNANCE_ACTION_TONES: Record<string, Tone> = {
  disable: 'danger',
  prioritize: 'success',
}

function governanceActionBadge(action: string): string {
  return TONE_BADGE[GOVERNANCE_ACTION_TONES[action] ?? 'neutral']
}

function SuggestionRow({ suggestion }: { suggestion: Suggestion }) {
  return (
    <div
      className={cn(
        'flex items-start gap-2 rounded-lg border px-3 py-2',
        suggestion.severity === 'warning' ? 'border-warning/30 bg-warning/10' : 'bg-muted/30',
      )}
    >
      <span
        className={cn(
          'shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold uppercase',
          governanceActionBadge(suggestion.action),
        )}
      >
        {suggestion.action}
      </span>
      <div className="min-w-0">
        <span className="font-mono text-xs text-foreground/80">{suggestion.tool}</span>
        <p className="text-xs leading-snug text-muted-foreground">{suggestion.reason}</p>
      </div>
    </div>
  )
}

const TD = 'px-3 py-2 align-top'
const TD_NUM = 'px-3 py-2 text-right align-top font-mono text-xs tabular-nums whitespace-nowrap'

function ToolTableRow({ tool }: { tool: Tool }) {
  const exercised = tool.call_count > 0
  return (
    <tr className="border-t">
      {/* Tool name + gating / unlock / unused-reason sublines */}
      <td className={TD}>
        <span
          className={cn(
            'font-mono text-sm',
            tool.enabled ? 'text-foreground/80' : 'text-muted-foreground/60 line-through',
          )}
        >
          {tool.name}
        </span>
        {tool.required_state_flags.length > 0 && (
          <p className="mt-0.5 font-mono text-xs text-warning">
            {COPY.requires} {tool.required_state_flags.join(', ')}
          </p>
        )}
        {tool.unlocks.length > 0 && (
          <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground/70">
            {COPY.unlocks} {tool.unlocks.join(', ')}
          </p>
        )}
        {!exercised && <p className="mt-0.5 text-xs italic text-muted-foreground/70">{unusedReason(tool)}</p>}
      </td>

      {/* Enabled / disabled */}
      <td className={TD}>
        <span className="inline-flex items-center gap-1.5 text-xs">
          <span className={cn('h-2 w-2 shrink-0 rounded-full', tool.enabled ? TONE_DOT.success : TONE_DOT.neutral)} />
          <span className="text-foreground/70">{tool.enabled ? COPY.on : COPY.off}</span>
        </span>
      </td>

      {/* Calls ledger */}
      <td className={TD_NUM}>
        {exercised ? (
          <span className="text-foreground/80">
            {tool.call_count}× · {tool.success_count} {COPY.ok}
          </span>
        ) : (
          <span className="italic text-muted-foreground/60">{COPY.unused}</span>
        )}
      </td>

      {/* Alpha attribution */}
      <td className={TD_NUM}>
        <span className={exercised ? sentimentTextClass(tool.alpha_score) : 'text-muted-foreground/70'}>
          {tool.alpha_score >= 0 ? '+' : ''}
          {tool.alpha_score.toFixed(2)}
        </span>
        {!exercised && <span className="ml-1 text-muted-foreground/60">{COPY.prior}</span>}
      </td>

      {/* Latency */}
      <td className={cn(TD_NUM, 'text-muted-foreground')}>{tool.latency_ms.toFixed(0)}ms</td>

      {/* Failure rate */}
      <td className={cn(TD_NUM, tool.failure_rate > 0.5 ? 'text-danger' : 'text-muted-foreground/70')}>
        {(tool.failure_rate * 100).toFixed(0)}%
      </td>
    </tr>
  )
}

function PhaseTable({ phase, tools }: { phase: string; tools: Tool[] }) {
  return (
    <div>
      <p className={cn(sectionTitleClass, 'mb-1')}>{phase}</p>
      <div className="overflow-x-auto rounded-lg border">
        <table className="min-w-full">
          <thead>
            <tr className="border-b bg-muted/50">
              {TOOL_COLUMNS.map((head, i) => (
                <th
                  key={head}
                  className={cn(
                    'px-3 py-2 text-xs font-semibold uppercase tracking-caps text-muted-foreground',
                    i === 0 ? 'text-left' : 'text-right',
                  )}
                >
                  {head}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tools.map((tool) => (
              <ToolTableRow key={tool.name} tool={tool} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function ToolGovernancePanel() {
  const { data, error } = usePolledApi<ToolRegistryResponse>(
    API_ENDPOINTS.DASHBOARD_TOOLS,
    LEARNING_REFRESH_MS,
  )

  const tools = data?.tools ?? []
  const suggestions = data?.suggestions ?? []
  const enabledCount = tools.filter((t) => t.enabled).length
  const exercisedCount = tools.filter((t) => t.call_count > 0).length
  const byPhase = PHASE_ORDER.map((phase) => ({
    phase,
    tools: tools.filter((t) => t.phase === phase),
  })).filter((group) => group.tools.length > 0)

  return (
    <div className={cardClass}>
      <div className="mb-1 flex items-center justify-between">
        <p className={sectionTitleClass}>{COPY.title}</p>
        {error ? (
          <span className={errorTextClass}>err: {error}</span>
        ) : (
          <span className="font-mono text-xs text-muted-foreground/70">
            {enabledCount}/{tools.length} {COPY.enabled}
          </span>
        )}
      </div>
      {/* One-line plain-language framing, then the column legend. */}
      <p className={cn(mutedClass, 'mb-1')}>{COPY.description}</p>
      <p className={cn(mutedClass, 'mb-3')}>
        {COPY.legend} {exercisedCount}/{tools.length} {COPY.haveRun}
      </p>

      {suggestions.length > 0 && (
        <div className="mb-4 space-y-2">
          <p className={sectionTitleClass}>{COPY.suggestionsTitle}</p>
          <p className="text-xs leading-snug text-muted-foreground/70">{COPY.suggestionsLegend}</p>
          {suggestions.map((s, i) => (
            <SuggestionRow key={`${s.tool}-${s.action}-${i}`} suggestion={s} />
          ))}
        </div>
      )}

      {tools.length === 0 ? (
        <p className="text-sm text-muted-foreground">{COPY.noTools}</p>
      ) : exercisedCount === 0 ? (
        // No telemetry yet: a full table of zeroed counters/prior alphas reads
        // as broken. Collapse to one explanatory state + the registered names.
        <div className="rounded-lg border border-dashed bg-muted/30 px-4 py-5 text-center">
          <p className="text-sm font-medium text-foreground/70">{COPY.noCallsTitle}</p>
          <p className="mx-auto mt-1 max-w-md text-xs leading-snug text-muted-foreground">
            {tools.length} {COPY.noCallsBodyPrefix} {COPY.noCallsBodySuffix}
          </p>
          <div className="mt-3 flex flex-wrap justify-center gap-1.5">
            {tools.map((tool) => (
              <span
                key={tool.name}
                title={`${tool.phase} · ${tool.enabled ? 'enabled' : 'disabled'}`}
                className={cn(
                  'rounded-md border bg-card px-2 py-0.5 font-mono text-2xs dark:bg-muted/50',
                  tool.enabled ? 'text-foreground/70' : 'text-muted-foreground/60 line-through',
                )}
              >
                {tool.name}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {byPhase.map((group) => (
            <PhaseTable key={group.phase} phase={group.phase} tools={group.tools} />
          ))}
        </div>
      )}
    </div>
  )
}
