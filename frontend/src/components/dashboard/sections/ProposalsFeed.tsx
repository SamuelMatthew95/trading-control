'use client'

import { Brain, ThumbsDown, ThumbsUp } from 'lucide-react'
import type { ComponentType, ReactNode } from 'react'
import { TerminalCard, SectionHeader, EmptyState } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, type Tone } from '@/lib/state'
import { formatRatioAsPercent, formatTimestamp } from '@/lib/format'
import { UI_TEXT } from '@/lib/constants/ui'
import {
  CHIP_BASE_BOLD,
  ICON_XS,
  MONO_CHIP,
  PENDING_COUNT_CHIP,
  ROW_START,
  ROW_WRAP,
  SCORE_CHIP,
  SCROLL_LIST_TALL,
  VOTE_BUTTON_BASE,
} from '@/lib/styles'
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

interface ProposalCardProps {
  proposal: Proposal
  onUpdateStatus: (id: string, status: ProposalStatus) => void
}

function proposalTypeLabel(type: string): string {
  return PROPOSAL_TYPE_LABEL[type] ?? type
}

function proposalTypeTone(type: string): Tone {
  return PROPOSAL_TYPE_TONE[type] ?? 'info'
}

function proposalDescription(content: string): string {
  return content?.trim() ? content : 'No description'
}

function proposalCardClass(status: ProposalStatus): string {
  return cn(
    'rounded-[6px] border p-3 transition-opacity',
    status === 'pending'
      ? 'border-slate-200 dark:border-slate-800/50'
      : 'border-slate-200 opacity-60 dark:border-slate-800',
  )
}

function pendingCount(proposals: Proposal[]): number {
  return proposals.filter((p) => p.status === 'pending').length
}

const VOTE_BUTTON_HOVER: Record<'pos' | 'neg', string> = {
  pos: 'hover:bg-emerald-500/20',
  neg: 'hover:bg-rose-500/20',
}

function VoteButton(props: {
  label: string
  Icon: ComponentType<{ className?: string }>
  tone: 'pos' | 'neg'
  onClick: () => void
}) {
  const { label, Icon, tone, onClick } = props
  return (
    <button
      onClick={onClick}
      className={cn(VOTE_BUTTON_BASE, TONE_CLASSES[tone].soft, VOTE_BUTTON_HOVER[tone])}
    >
      <Icon className={ICON_XS} />
      {label}
    </button>
  )
}

function VoteControls(props: { proposalId: string; onUpdateStatus: ProposalCardProps['onUpdateStatus'] }) {
  const { proposalId, onUpdateStatus } = props
  const onApprove = () => onUpdateStatus(proposalId, 'approved')
  const onReject = () => onUpdateStatus(proposalId, 'rejected')
  return (
    <div className={ROW_START}>
      <VoteButton label="Approve" Icon={ThumbsUp} tone="pos" onClick={onApprove} />
      <VoteButton label="Reject" Icon={ThumbsDown} tone="neg" onClick={onReject} />
    </div>
  )
}

function StatusBadge(props: { status: Exclude<ProposalStatus, 'pending'> }) {
  const tone = props.status === 'approved' ? 'pos' : 'neg'
  return <span className={cn(SCORE_CHIP, 'uppercase', TONE_CLASSES[tone].soft)}>{props.status}</span>
}

const PROPOSAL_HEADER = cn('mb-2', ROW_WRAP)

function ProposalHeader(props: { proposal: Proposal }) {
  const { proposal } = props
  const tone = proposalTypeTone(proposal.proposal_type)
  return (
    <div className={PROPOSAL_HEADER}>
      <span className={cn(CHIP_BASE_BOLD, TONE_CLASSES[tone].soft)}>
        {proposalTypeLabel(proposal.proposal_type)}
      </span>
      {proposal.confidence != null ? (
        <span className={MONO_CHIP}>{formatRatioAsPercent(proposal.confidence)} confidence</span>
      ) : null}
      {proposal.status !== 'pending' ? <StatusBadge status={proposal.status} /> : null}
      <span className={cn(UI_TEXT.muted, 'ml-auto')}>{formatTimestamp(proposal.timestamp)}</span>
    </div>
  )
}

function ProposalCard(props: ProposalCardProps) {
  const { proposal, onUpdateStatus } = props
  const showVoteControls = proposal.status === 'pending' && proposal.requires_approval
  return (
    <div className={proposalCardClass(proposal.status)}>
      <ProposalHeader proposal={proposal} />
      <p className={cn(UI_TEXT.body, 'mb-2 leading-relaxed')}>
        {proposalDescription(proposal.content)}
      </p>
      {showVoteControls ? (
        <VoteControls proposalId={proposal.id} onUpdateStatus={onUpdateStatus} />
      ) : null}
    </div>
  )
}

function PendingBadge(props: { count: number }): ReactNode {
  if (props.count === 0) return null
  return <span className={PENDING_COUNT_CHIP}>{props.count} pending</span>
}

export function ProposalsFeed(props: ProposalsFeedProps) {
  const { proposals, onUpdateStatus } = props
  const pending = pendingCount(proposals)
  return (
    <TerminalCard>
      <SectionHeader
        title="Strategy Proposals"
        icon={Brain}
        right={
          <>
            <PendingBadge count={pending} />
            <span className={UI_TEXT.muted}>{proposals.length} total</span>
          </>
        }
      />
      {proposals.length === 0 ? (
        <EmptyState message="No proposals yet" icon={Brain} />
      ) : (
        <div className={SCROLL_LIST_TALL}>
          {proposals.map((proposal) => (
            <ProposalCard key={proposal.id} proposal={proposal} onUpdateStatus={onUpdateStatus} />
          ))}
        </div>
      )}
    </TerminalCard>
  )
}
