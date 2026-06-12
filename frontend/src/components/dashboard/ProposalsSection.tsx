'use client'

import { useMemo, useState } from 'react'
import { Check, X } from 'lucide-react'

import { api } from '@/lib/apiClient'
import { formatPercent } from '@/lib/formatters'
import { proposalStatusClass } from '@/lib/dashboard-helpers'
import { cardClass, mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { proposalRouting, type ProposalRouting } from '@/lib/proposal-routing'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { PROPOSAL_APPROVED, PROPOSAL_PENDING, PROPOSAL_REJECTED } from '@/constants/trading'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { cn } from '@/lib/utils'
import { useDashboardStore, type Proposal } from '@/stores/useDashboardStore'
import { ProposalDetailModal } from '@/components/dashboard/ProposalDetailModal'

/**
 * Routing destinations are a five-way categorical legend (config PR / issue /
 * review / system-applied / unknown) that the four semantic Tones cannot
 * express — hence the per-line categorical hue escapes.
 */
function routingBadgeClass(kind: ProposalRouting['kind']): string {
  if (kind === 'config-pr')
    return 'border-sky-400/30 bg-sky-400/10 text-sky-700 dark:text-sky-300' // categorical-hue: proposal routing legend
  if (kind === 'issue')
    return 'border-violet-400/30 bg-violet-400/10 text-violet-700 dark:text-violet-300' // categorical-hue: proposal routing legend
  if (kind === 'unknown')
    return 'border-muted-foreground/30 bg-muted-foreground/10 text-foreground/70'
  if (kind === 'review')
    // challenger promotion — auto-applies by default (gate restorable via
    // CHALLENGER_PROMOTION_AUTO_APPLY=false); distinct from grey "unknown"
    return 'border-indigo-400/30 bg-indigo-400/10 text-indigo-700 dark:text-indigo-300' // categorical-hue: proposal routing legend
  // control-plane / prompt / tool / mixed are all system-applied state changes
  return 'border-teal-400/30 bg-teal-400/10 text-teal-700 dark:text-teal-300' // categorical-hue: proposal routing legend
}

function proposalLabel(proposal: Proposal): string {
  return proposal.content || proposal.strategy_name || proposal.proposal_type.replace(/_/g, ' ')
}

function EmptyProposals() {
  return (
    <EmptyState
      message={UI_COPY.proposalQueue.emptyTitle}
      className="px-4 py-6"
      hint={
        <>
          <p>{UI_COPY.proposalQueue.emptyIntro}</p>
          <ul className="mx-auto mt-3 max-w-xl space-y-1.5 text-left">
            {UI_COPY.proposalQueue.emptySources.map(({ term, body }) => (
              <li key={term}>
                <span className="font-semibold text-foreground/70">{term}</span> {body}
              </li>
            ))}
          </ul>
        </>
      }
    />
  )
}

export function ProposalsSection() {
  const proposals = useDashboardStore((state) => state.proposals)
  const updateProposalStatus = useDashboardStore((state) => state.updateProposalStatus)
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  // Drill-down: which proposal's detail modal is open (null = none).
  const [selectedProposal, setSelectedProposal] = useState<Proposal | null>(null)

  const summary = useMemo(
    () => ({
      pending: proposals.filter((proposal) => proposal.status === PROPOSAL_PENDING).length,
      approved: proposals.filter((proposal) => proposal.status === PROPOSAL_APPROVED).length,
      rejected: proposals.filter((proposal) => proposal.status === PROPOSAL_REJECTED).length,
    }),
    [proposals],
  )

  const handleVote = async (id: string, vote: 'approve' | 'reject') => {
    setPendingAction(id)
    const status = vote === 'approve' ? PROPOSAL_APPROVED : PROPOSAL_REJECTED
    try {
      const response = await fetch(api(`/dashboard/learning/proposals/${encodeURIComponent(id)}`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      if (response.ok) updateProposalStatus(id, status)
    } catch {
      // network failure — leave proposal in current state
    } finally {
      setPendingAction(null)
    }
  }

  return (
    <section className={cardClass}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className={sectionTitleClass}>{UI_COPY.proposalQueue.title}</p>
          <p className="mt-1 text-xs text-muted-foreground">{UI_COPY.proposalQueue.subtitle}</p>
        </div>
        <div className="flex flex-wrap gap-2 font-mono text-3xs uppercase tracking-caps">
          <span className="rounded border border-warning/30 bg-warning/10 px-2 py-1 text-warning">
            {UI_COPY.proposalQueue.pending} {summary.pending}
          </span>
          <span className="rounded border border-success/30 bg-success/10 px-2 py-1 text-success">
            {UI_COPY.proposalQueue.approved} {summary.approved}
          </span>
          <span className="rounded border border-danger/30 bg-danger/10 px-2 py-1 text-danger">
            {UI_COPY.proposalQueue.rejected} {summary.rejected}
          </span>
        </div>
      </div>

      {proposals.length === 0 ? (
        <EmptyProposals />
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[860px] text-left text-xs">
            <thead className="bg-muted/60 text-3xs uppercase tracking-caps text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-semibold">{UI_COPY.proposalQueue.columns.change}</th>
                <th className="px-3 py-2 font-semibold">{UI_COPY.proposalQueue.columns.type}</th>
                <th className="px-3 py-2 font-semibold">{UI_COPY.proposalQueue.columns.onApprove}</th>
                <th className="px-3 py-2 font-semibold">{UI_COPY.proposalQueue.columns.expected}</th>
                <th className="px-3 py-2 font-semibold">{UI_COPY.proposalQueue.columns.backtestDelta}</th>
                <th className="px-3 py-2 font-semibold">{UI_COPY.proposalQueue.columns.traceability}</th>
                <th className="px-3 py-2 font-semibold">{UI_COPY.proposalQueue.columns.status}</th>
                <th className="px-3 py-2 text-right font-semibold">{UI_COPY.proposalQueue.columns.decision}</th>
              </tr>
            </thead>
            <tbody className="divide-y bg-card dark:bg-card/50">
              {proposals.map((proposal) => {
                const isPending = proposal.status === PROPOSAL_PENDING
                return (
                  <tr key={proposal.id} className="align-top text-foreground/70">
                    <td className="max-w-[360px] px-3 py-2">
                      <button
                        type="button"
                        onClick={() => setSelectedProposal(proposal)}
                        title={UI_COPY.proposalQueue.detailsTitle}
                        className="text-left"
                      >
                        <p className="line-clamp-2 font-medium text-foreground underline-offset-2 hover:underline">
                          {proposalLabel(proposal)}
                        </p>
                        <p className={cn(mutedClass, 'mt-1')}>
                          ID {proposal.id} · {UI_COPY.proposalQueue.detailsLink}
                        </p>
                      </button>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {proposal.proposal_type.replace(/_/g, ' ')}
                    </td>
                    <td className="px-3 py-2">
                      {(() => {
                        const routing = proposalRouting(proposal.proposal_type)
                        return (
                          <span
                            title={routing.hint}
                            className={cn(
                              'inline-block rounded border px-2 py-1 font-mono text-3xs uppercase tracking-caps',
                              routingBadgeClass(routing.kind),
                            )}
                          >
                            {routing.label}
                          </span>
                        )
                      })()}
                    </td>
                    <td className="px-3 py-2 font-mono text-foreground/70">
                      {formatPercent(proposal.confidence)}
                    </td>
                    <td className="px-3 py-2 font-mono text-foreground/70">
                      {proposal.grade_score != null ? formatPercent(proposal.grade_score) : NO_DATA}
                    </td>
                    <td className="px-3 py-2 font-mono text-2xs text-muted-foreground">
                      {proposal.reflection_trace_id || proposal.trace_id ? (
                        <span>
                          {String(proposal.reflection_trace_id ?? proposal.trace_id).slice(0, 18)}…
                        </span>
                      ) : (
                        NO_DATA
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={cn(
                          'rounded border border-transparent px-2 py-1 font-mono text-3xs uppercase',
                          proposalStatusClass(proposal.status),
                        )}
                        title={
                          proposal.applied
                            ? `${UI_COPY.proposalQueue.appliedByPrefix}${proposal.applied_at ? ` at ${proposal.applied_at}` : ''}`
                            : undefined
                        }
                      >
                        {proposal.applied ? UI_COPY.proposalQueue.applied : proposal.status}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {isPending ? (
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="tonal"
                            tone="success"
                            size="xs"
                            disabled={pendingAction === proposal.id}
                            onClick={() => handleVote(proposal.id, 'approve')}
                            className="font-semibold"
                          >
                            <Check className="h-3 w-3" aria-hidden /> {UI_COPY.actions.approve}
                          </Button>
                          <Button
                            variant="tonal"
                            tone="danger"
                            size="xs"
                            disabled={pendingAction === proposal.id}
                            onClick={() => handleVote(proposal.id, 'reject')}
                            className="font-semibold"
                          >
                            <X className="h-3 w-3" aria-hidden /> {UI_COPY.actions.reject}
                          </Button>
                        </div>
                      ) : (
                        <p className="text-right text-2xs text-muted-foreground">
                          {UI_COPY.proposalQueue.reviewed}
                        </p>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {selectedProposal && (
        <ProposalDetailModal proposal={selectedProposal} onClose={() => setSelectedProposal(null)} />
      )}
    </section>
  )
}
