'use client'

import { Brain, ThumbsDown, ThumbsUp } from 'lucide-react'
import type { ComponentType, ReactNode } from 'react'
import { TerminalCard, SectionHeader, EmptyState } from '@/components/terminal'
import { cn } from '@/lib/utils'
import { TONE_CLASSES, type Tone } from '@/lib/state'
import { extractConfidence, formatRatioAsPercent, formatTimestamp } from '@/lib/format'
import { PROPOSAL_TYPE_LABEL, PROPOSAL_TYPE_TONE } from '@/lib/constants/learning'
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

interface ProposalsFeedProps {
  proposals: Proposal[]
  onUpdateStatus: (id: string, status: ProposalStatus) => void
  /** IDs of proposals whose vote API call is currently in flight. */
  pendingVoteIds?: ReadonlySet<string>
}

interface ProposalCardProps {
  proposal: Proposal
  onUpdateStatus: (id: string, status: ProposalStatus) => void
  /** True while the API request for this proposal's vote is in flight. */
  isVoting: boolean
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
  disabled: boolean
}) {
  const { label, Icon, tone, onClick, disabled } = props
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-busy={disabled}
      className={cn(
        VOTE_BUTTON_BASE,
        TONE_CLASSES[tone].soft,
        VOTE_BUTTON_HOVER[tone],
        'disabled:cursor-not-allowed disabled:opacity-50',
      )}
    >
      <Icon className={ICON_XS} />
      {label}
    </button>
  )
}

interface VoteControlsProps {
  proposalId: string
  onUpdateStatus: ProposalCardProps['onUpdateStatus']
  isVoting: boolean
}

function VoteControls(props: VoteControlsProps) {
  const { proposalId, onUpdateStatus, isVoting } = props
  // Guard at the handler level too — if a click somehow lands while the
  // button is mid-disable transition, swallow it. Belt and suspenders.
  const onApprove = () => {
    if (isVoting) return
    onUpdateStatus(proposalId, 'approved')
  }
  const onReject = () => {
    if (isVoting) return
    onUpdateStatus(proposalId, 'rejected')
  }
  return (
    <div className={ROW_START}>
      <VoteButton
        label={isVoting ? 'Working…' : 'Approve'}
        Icon={ThumbsUp}
        tone="pos"
        onClick={onApprove}
        disabled={isVoting}
      />
      <VoteButton
        label="Reject"
        Icon={ThumbsDown}
        tone="neg"
        onClick={onReject}
        disabled={isVoting}
      />
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
  // Use the centralized confidence extractor — handles both 0-1 and 0-100
  // shapes plus the alternate `confidence_score` field name.
  const confidence = extractConfidence(proposal as unknown as Record<string, unknown>)
  return (
    <div className={PROPOSAL_HEADER}>
      <span className={cn(CHIP_BASE_BOLD, TONE_CLASSES[tone].soft)}>
        {proposalTypeLabel(proposal.proposal_type)}
      </span>
      {confidence != null ? (
        <span className={MONO_CHIP}>{formatRatioAsPercent(confidence)} confidence</span>
      ) : null}
      {proposal.status !== 'pending' ? <StatusBadge status={proposal.status} /> : null}
      <span className={cn(UI_TEXT.muted, 'ml-auto')}>{formatTimestamp(proposal.timestamp)}</span>
    </div>
  )
}

function ProposalCard(props: ProposalCardProps) {
  const { proposal, onUpdateStatus, isVoting } = props
  const showVoteControls = proposal.status === 'pending' && proposal.requires_approval
  return (
    <div className={proposalCardClass(proposal.status)}>
      <ProposalHeader proposal={proposal} />
      <p className={cn(UI_TEXT.body, 'mb-2 leading-relaxed')}>
        {proposalDescription(proposal.content)}
      </p>
      {showVoteControls ? (
        <VoteControls
          proposalId={proposal.id}
          onUpdateStatus={onUpdateStatus}
          isVoting={isVoting}
        />
      ) : null}
    </div>
  )
}

function PendingBadge(props: { count: number }): ReactNode {
  if (props.count === 0) return null
  return <span className={PENDING_COUNT_CHIP}>{props.count} pending</span>
}

export function ProposalsFeed(props: ProposalsFeedProps) {
  const { proposals, onUpdateStatus, pendingVoteIds } = props
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
            <ProposalCard
              key={proposal.id}
              proposal={proposal}
              onUpdateStatus={onUpdateStatus}
              isVoting={pendingVoteIds?.has(proposal.id) ?? false}
            />
          ))}
        </div>
      )}
    </TerminalCard>
  )
}
