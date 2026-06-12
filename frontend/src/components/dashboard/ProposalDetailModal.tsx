'use client'

import { formatPercent } from '@/lib/formatters'
import { proposalStatusTone } from '@/lib/dashboard-helpers'
import { mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { proposalRouting } from '@/lib/proposal-routing'
import { cn } from '@/lib/utils'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { Modal } from '@/components/ui/modal'
import { Badge } from '@/components/ui/badge'
import { MetricTile } from '@/components/ui/stat-tile'
import type { Proposal } from '@/stores/useDashboardStore'

/**
 * Proposal drill-in — the full candidate change, what happens on approve, the
 * backtest evidence, and traceability. Reads the proposal already in the store
 * (no fetch), so "click → view → learn" works in DB and memory mode alike.
 */
export function ProposalDetailModal({
  proposal,
  onClose,
}: {
  proposal: Proposal
  onClose: () => void
}) {
  const routing = proposalRouting(proposal.proposal_type)
  const content =
    proposal.content || proposal.strategy_name || proposal.proposal_type.replace(/_/g, ' ')

  return (
    <Modal
      onClose={onClose}
      title={`${UI_COPY.proposalDetail.title} · ${proposal.proposal_type.replace(/_/g, ' ')}`}
      subtitle={
        <div className="flex items-center gap-3">
          <p className={cn(mutedClass, 'font-mono')}>
            {UI_COPY.proposalDetail.id} {proposal.id}
          </p>
          <Badge
            tone={proposalStatusTone(proposal.status)}
            variant="outlined"
            className="font-mono text-3xs uppercase"
          >
            {proposal.status}
          </Badge>
        </div>
      }
    >
      {/* What it is */}
      <Section label={UI_COPY.proposalDetail.candidateChange}>
        <p className="whitespace-pre-wrap text-sm text-foreground/90">{content}</p>
      </Section>

      {/* What happens on approve — plain English */}
      <Section label={UI_COPY.proposalDetail.onApprove}>
        <p className="text-sm text-foreground/80">{routing.hint}</p>
        <p className={cn(mutedClass, 'mt-1')}>
          {UI_COPY.proposalDetail.routesTo} {routing.label}
        </p>
      </Section>

      {/* Evidence */}
      <Section label={UI_COPY.proposalDetail.evidence}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <MetricTile label={UI_COPY.proposalDetail.confidence} value={formatPercent(proposal.confidence)} />
          <MetricTile
            label={UI_COPY.proposalDetail.backtestDelta}
            value={proposal.grade_score != null ? formatPercent(proposal.grade_score) : NO_DATA}
          />
          <MetricTile
            label={UI_COPY.proposalDetail.requiresApproval}
            value={proposal.requires_approval ? UI_COPY.proposalDetail.yes : UI_COPY.proposalDetail.no}
          />
        </div>
      </Section>

      {/* Provenance */}
      <Section label={UI_COPY.proposalDetail.traceability}>
        <dl className="grid grid-cols-1 gap-1 font-mono text-2xs text-muted-foreground">
          <Row k="trace_id" v={proposal.trace_id} />
          <Row k="reflection_trace_id" v={proposal.reflection_trace_id} />
          <Row k="source" v={proposal.source} />
          <Row k="symbol" v={proposal.symbol} />
          <Row k="created_at" v={proposal.created_at ?? proposal.timestamp} />
        </dl>
      </Section>
    </Modal>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <p className={cn(sectionTitleClass, 'mb-1.5')}>{label}</p>
      {children}
    </div>
  )
}

function Row({ k, v }: { k: string; v?: string | null }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="shrink-0">{k}</dt>
      <dd className="truncate text-foreground/70">{v || NO_DATA}</dd>
    </div>
  )
}
