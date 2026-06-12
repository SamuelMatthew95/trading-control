'use client'

import { API_ENDPOINTS } from '@/lib/apiClient'
import { usePolledApi } from '@/hooks/usePolledApi'
import { formatTimeAgo } from '@/lib/formatters'
import { LEARNING_REFRESH_MS } from '@/lib/grade-colors'
import { cardClass, errorTextClass, mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { UI_COPY } from '@/constants/copy'
import { cn } from '@/lib/utils'

// Mirrors api.services.prompt_store.PromptStore directive records.
interface Directive {
  node: string
  text: string
  version: number
  rationale?: string
  source?: string
  updated_at?: string
}

// Mirrors api.services.dashboard.prompt_evolution.get_prompt_evolution_payload.
interface PromptEvolutionResponse {
  node: string
  active: Directive | null
  history: Directive[]
  version: number
  enabled: boolean
  auto_apply: boolean
}

const COPY = UI_COPY.promptEvolution

function VersionTag({ version }: { version: number }) {
  return (
    <span className="shrink-0 rounded bg-brand/15 px-1.5 py-0.5 font-mono text-3xs font-semibold text-brand">
      v{version}
    </span>
  )
}

// Provenance line: WHERE a directive version came from (e.g. PROPOSAL_APPLIER
// for a challenger promotion, or reflection for an LLM-evolved one) and WHEN —
// so the operator can read the full lineage of past + current, not just text.
function MetaLine({ source, updatedAt }: { source?: string; updatedAt?: string }) {
  const ago = formatTimeAgo(updatedAt)
  if (!source && !ago) return null
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-3xs text-muted-foreground/70">
      {source && (
        <span className="rounded bg-muted-foreground/10 px-1.5 py-0.5 font-mono uppercase tracking-caps">
          {source}
        </span>
      )}
      {ago && <span>{ago}</span>}
    </div>
  )
}

export function PromptEvolutionPanel() {
  const { data, error } = usePolledApi<PromptEvolutionResponse>(
    API_ENDPOINTS.DASHBOARD_PROMPT_EVOLUTION,
    LEARNING_REFRESH_MS,
  )

  const active = data?.active ?? null
  const history = data?.history ?? []

  return (
    <div className={cardClass}>
      <div className="mb-1 flex items-center justify-between">
        <p className={sectionTitleClass}>{COPY.title}</p>
        {error ? (
          <span className={errorTextClass}>err: {error}</span>
        ) : (
          <span className="flex items-center gap-2 font-mono text-xs text-muted-foreground/70">
            <span
              className={cn(
                'rounded px-1.5 py-0.5 text-3xs font-semibold uppercase',
                data?.enabled ? 'bg-success/15 text-success' : 'bg-muted-foreground/15 text-muted-foreground',
              )}
            >
              {data?.enabled ? COPY.evolving : COPY.frozen}
            </span>
            {data?.auto_apply ? COPY.autoApply : COPY.manual}
          </span>
        )}
      </div>
      <p className={cn(mutedClass, 'mb-3')}>{COPY.description}</p>

      {!active ? (
        <div className="space-y-2 text-xs text-muted-foreground">
          <p>
            {COPY.emptyIntroPrefix}{' '}
            <span className="font-medium text-foreground/70">{COPY.emptyIntroConstitution}</span>{' '}
            {COPY.emptyIntroSuffix}
          </p>
          <ol className="space-y-1">
            {[
              COPY.step1,
              COPY.step2,
              COPY.step3,
              `${COPY.step4Prefix} ${data?.auto_apply ? COPY.autoApply : COPY.step4Approval} ${COPY.step4Stem}`,
            ].map((step, i) => (
              <li key={i} className="flex gap-2">
                <span className="font-mono text-muted-foreground/70">{i + 1}</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
          <p className="italic">{data?.enabled ? COPY.warmingUp : COPY.frozenHint}</p>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="rounded-lg border border-brand/30 bg-brand/5 px-3 py-2">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="text-2xs font-semibold uppercase tracking-caps text-brand">
                {COPY.active}
              </span>
              <VersionTag version={active.version} />
            </div>
            {/* Bounded — a long directive scrolls inside the card instead of
                stretching the page into a wall of text. */}
            <p className="max-h-48 overflow-y-auto whitespace-pre-wrap text-xs leading-snug text-foreground/90">
              {active.text}
            </p>
            {active.rationale && (
              <p className="mt-1.5 text-2xs italic text-muted-foreground">
                {COPY.why} {active.rationale}
              </p>
            )}
            <MetaLine source={active.source} updatedAt={active.updated_at} />
          </div>

          {history.length > 0 && (
            <div>
              <p className={cn(sectionTitleClass, 'mb-1.5')}>
                {COPY.historyPrefix} {history.length}{' '}
                {history.length === 1 ? COPY.priorVersion : COPY.priorVersions}
              </p>
              {/* Collapsed by default: prior versions are audit material, not
                  reading material — full text only on expand. */}
              <div className="space-y-1.5">
                {history.map((d) => (
                  <details key={d.version} className="group rounded-lg border">
                    <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-2xs text-muted-foreground marker:content-none [&::-webkit-details-marker]:hidden">
                      <span className="text-muted-foreground/60 transition-transform group-open:rotate-90">
                        ▸
                      </span>
                      <VersionTag version={d.version} />
                      <span className="flex-1 truncate italic">{d.rationale || COPY.noRationale}</span>
                      <span className="shrink-0 font-mono text-3xs text-muted-foreground/70">
                        {formatTimeAgo(d.updated_at)}
                      </span>
                    </summary>
                    <div className="border-t px-3 py-2">
                      <p className="max-h-40 overflow-y-auto whitespace-pre-wrap text-2xs leading-snug text-foreground/70">
                        {d.text}
                      </p>
                      <MetaLine source={d.source} updatedAt={d.updated_at} />
                    </div>
                  </details>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
