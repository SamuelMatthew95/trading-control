'use client'

import { useState } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'
import { api } from '@/lib/apiClient'
import { cn } from '@/lib/utils'
import { cardClass, sectionTitleClass, mutedClass } from '@/lib/dashboard-styles'
import { Zap } from 'lucide-react'

function EmptyProposals() {
  return (
    <div className="flex min-h-28 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/50 px-4 py-10 dark:border-slate-800 dark:bg-slate-900/30">
      <Zap className="h-5 w-5 text-slate-300 dark:text-slate-600" />
      <p className="text-xs font-sans font-medium text-slate-400 dark:text-slate-600">
        No proposals yet — they arrive from the ReflectionAgent
      </p>
    </div>
  )
}

export function ProposalsSection() {
  const proposals = useCodexStore((state) => state.proposals)
  const updateProposalStatus = useCodexStore((state) => state.updateProposalStatus)
  const [pendingAction, setPendingAction] = useState<string | null>(null)

  const handleVote = async (id: string, vote: 'approve' | 'reject') => {
    setPendingAction(id)
    const status = vote === 'approve' ? ('approved' as const) : ('rejected' as const)
    try {
      const response = await fetch(
        api(`/dashboard/learning/proposals/${encodeURIComponent(id)}`),
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status }),
        },
      )
      if (response.ok) updateProposalStatus(id, status)
    } catch {
      // network failure — leave proposal in current state
    } finally {
      setPendingAction(null)
    }
  }

  return (
    <div className={cardClass}>
      <p className={cn(sectionTitleClass, 'mb-3')}>Strategy Proposals</p>
      {proposals.length === 0 ? (
        <EmptyProposals />
      ) : (
        <div className="space-y-3">
          {proposals.map((p) => {
            const isPending = p.status === 'pending'
            const isApproved = p.status === 'approved'
            const confidencePct =
              p.confidence != null ? `${(p.confidence * 100).toFixed(0)}%` : null
            return (
              <div
                key={p.id}
                className={cn(
                  'rounded-lg border p-3',
                  isApproved
                    ? 'border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/30'
                    : p.status === 'rejected'
                      ? 'border-slate-200 bg-slate-50 opacity-60 dark:border-slate-700 dark:bg-slate-800/30'
                      : 'border-slate-200 dark:border-slate-800',
                )}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded bg-slate-500/10 px-2 py-0.5 text-xs font-semibold text-slate-500">
                        {p.proposal_type.replace(/_/g, ' ')}
                      </span>
                      {confidencePct && <span className={mutedClass}>{confidencePct} confidence</span>}
                    </div>
                    <p className="line-clamp-3 text-sm leading-snug text-slate-700 dark:text-slate-300">
                      {p.content || '--'}
                    </p>
                    {p.reflection_trace_id && (
                      <p className="truncate font-mono text-[10px] text-slate-400">
                        trace: {p.reflection_trace_id.slice(0, 16)}…
                      </p>
                    )}
                  </div>
                  {isPending ? (
                    <div className="flex shrink-0 gap-2">
                      <button
                        disabled={pendingAction === p.id}
                        onClick={() => handleVote(p.id, 'approve')}
                        className="rounded bg-emerald-500 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-600 disabled:opacity-50"
                      >
                        Approve
                      </button>
                      <button
                        disabled={pendingAction === p.id}
                        onClick={() => handleVote(p.id, 'reject')}
                        className="rounded bg-rose-500 px-3 py-1 text-xs font-semibold text-white hover:bg-rose-600 disabled:opacity-50"
                      >
                        Reject
                      </button>
                    </div>
                  ) : (
                    <span
                      className={cn(
                        'shrink-0 rounded px-2 py-1 text-xs font-semibold',
                        isApproved
                          ? 'bg-emerald-500/15 text-emerald-600'
                          : 'bg-slate-500/15 text-slate-500',
                      )}
                    >
                      {p.status}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
