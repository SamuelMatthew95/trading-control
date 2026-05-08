'use client'

import { Brain, ThumbsDown, ThumbsUp } from 'lucide-react'
import { TerminalCard, SectionHeader, EmptyState } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, type Tone } from '@/lib/state'
import { formatRatioAsPercent, formatTimestamp } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import type { Proposal, ProposalStatus } from '@/stores/useCodexStore'

const PROPOSAL_TYPE_LABEL: Record<string, string> = {
  parameter_change: 'Param Change',
  code_change: 'Code Change',
  regime_adjustment: 'Regime Adjust',
  signal_weight_reduction: 'Weight Reduction',
  agent_suspension: 'Suspension',
  agent_retirement: 'Retirement',
  new_agent: 'New Agent',
}

const PROPOSAL_TYPE_TONE: Record<string, Tone> = {
  parameter_change: 'info',
  code_change: 'info',
  regime_adjustment: 'warn',
  signal_weight_reduction: 'warn',
  agent_suspension: 'neg',
  agent_retirement: 'neg',
  new_agent: 'pos',
}

interface ProposalsFeedProps {
  proposals: Proposal[]
  onUpdateStatus: (id: string, status: ProposalStatus) => void
}

export function ProposalsFeed({ proposals, onUpdateStatus }: ProposalsFeedProps) {
  const pending = proposals.filter((p) => p.status === 'pending')
  return (
    <TerminalCard>
      <SectionHeader
        title="Strategy Proposals"
        icon={Brain}
        right={
          <>
            {pending.length > 0 ? (
              <span className="rounded-[4px] bg-slate-200 px-2 py-0.5 text-xs font-bold text-slate-900 dark:bg-slate-700 dark:text-slate-100">
                {pending.length} pending
              </span>
            ) : null}
            <span className={UI_TEXT.muted}>{proposals.length} total</span>
          </>
        }
      />
      {proposals.length === 0 ? (
        <EmptyState message="No proposals yet" icon={Brain} />
      ) : (
        <div className="max-h-96 space-y-3 overflow-y-auto">
          {proposals.map((proposal) => (
            <ProposalCard
              key={proposal.id}
              proposal={proposal}
              onUpdateStatus={onUpdateStatus}
            />
          ))}
        </div>
      )}
    </TerminalCard>
  )
}

interface ProposalCardProps {
  proposal: Proposal
  onUpdateStatus: (id: string, status: ProposalStatus) => void
}

function ProposalCard({ proposal, onUpdateStatus }: ProposalCardProps) {
  const typeTone = PROPOSAL_TYPE_TONE[proposal.proposal_type] ?? 'info'
  const typeLabel = PROPOSAL_TYPE_LABEL[proposal.proposal_type] ?? proposal.proposal_type
  const description = proposal.content?.trim() || 'No description'

  return (
    <div
      className={cn(
        'rounded-[6px] border p-3 transition-opacity',
        proposal.status === 'pending'
          ? 'border-slate-200 dark:border-slate-800/50'
          : 'border-slate-200 opacity-60 dark:border-slate-800',
      )}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className={cn('rounded-[4px] px-2 py-0.5 text-xs font-bold', TONE_CLASSES[typeTone].soft)}>
          {typeLabel}
        </span>
        {proposal.confidence != null ? (
          <span className="rounded-[4px] bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-500 dark:bg-slate-800">
            {formatRatioAsPercent(proposal.confidence)} confidence
          </span>
        ) : null}
        {proposal.status !== 'pending' ? (
          <span
            className={cn(
              'rounded-[4px] px-2 py-0.5 text-xs font-semibold uppercase',
              proposal.status === 'approved' ? TONE_CLASSES.pos.soft : TONE_CLASSES.neg.soft,
            )}
          >
            {proposal.status}
          </span>
        ) : null}
        <span className={cn(UI_TEXT.muted, 'ml-auto')}>{formatTimestamp(proposal.timestamp)}</span>
      </div>
      <p className={cn(UI_TEXT.body, 'mb-2 leading-relaxed')}>{description}</p>
      {proposal.status === 'pending' && proposal.requires_approval ? (
        <div className="flex items-center gap-2">
          <button
            onClick={() => onUpdateStatus(proposal.id, 'approved')}
            className={cn(
              'flex items-center gap-1.5 rounded-[4px] px-3 py-1 text-xs font-semibold transition-colors',
              TONE_CLASSES.pos.soft,
              'hover:bg-emerald-500/20',
            )}
          >
            <ThumbsUp className="h-3 w-3" />
            Approve
          </button>
          <button
            onClick={() => onUpdateStatus(proposal.id, 'rejected')}
            className={cn(
              'flex items-center gap-1.5 rounded-[4px] px-3 py-1 text-xs font-semibold transition-colors',
              TONE_CLASSES.neg.soft,
              'hover:bg-rose-500/20',
            )}
          >
            <ThumbsDown className="h-3 w-3" />
            Reject
          </button>
        </div>
      ) : null}
    </div>
  )
}
