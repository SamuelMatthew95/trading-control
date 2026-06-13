'use client'

import { ArrowRight } from 'lucide-react'

import { cn } from '@/lib/utils'
import { NO_DATA } from '@/constants/copy'
import { signed, statusTone } from '@/lib/cognitive'
import type { CognitiveSnapshot } from '@/types/cognitive'

import { card, chip, CMD, COPY, Grade, subTableHeadClass } from './cognitive-ui'

export function ProposalsPanel({ snap }: { snap: CognitiveSnapshot }) {
  if (snap.proposals.length === 0) {
    return <div className={cn(card, 'text-sm text-muted-foreground')}>{COPY.proposalsEmpty}</div>
  }
  return (
    <div className={cn(card, 'overflow-x-auto p-0')}>
      <table className="w-full min-w-[840px] text-left text-xs">
        <thead className={subTableHeadClass}>
          <tr>
            <th className="px-3 py-2 font-semibold">{COPY.columns.proposal}</th>
            <th className="px-3 py-2 font-semibold">{COPY.columns.change}</th>
            <th className="px-3 py-2 font-semibold">{COPY.columns.backtestDelta}</th>
            <th className="px-3 py-2 font-semibold">{COPY.columns.verdict}</th>
            <th className="px-3 py-2 font-semibold">{COPY.columns.status}</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {snap.proposals.map((entry) => {
            const { proposal, verdict, delta, status, proposal_grade } = entry
            return (
              <tr key={proposal.proposal_id} className="align-top text-foreground/70">
                <td className="px-3 py-2">
                  <p className="font-mono text-2xs text-muted-foreground">{proposal.proposal_id}</p>
                  <p className="mt-1 text-muted-foreground">{proposal.proposal_type}</p>
                </td>
                <td className="px-3 py-2">
                  <p className="flex flex-wrap items-center gap-1 font-mono text-sm">
                    <span className="text-muted-foreground">{proposal.target}:</span>
                    <span className="text-danger">{String(proposal.old_value)}</span>
                    <ArrowRight className="h-3 w-3 text-muted-foreground" aria-hidden />
                    <span className="text-success">{String(proposal.new_value)}</span>
                  </p>
                  <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{proposal.reason}</p>
                </td>
                <td className="px-3 py-2 font-mono text-2xs text-muted-foreground">
                  {delta ? (
                    <span>
                      {COPY.deltaPnl} {signed(delta.pnl_delta)}
                      {CMD.pctSuffix} · {COPY.deltaSharpe} {signed(delta.sharpe_delta)} ·{' '}
                      {COPY.deltaDrawdown} {signed(delta.drawdown_delta)}
                      {CMD.pctSuffix}
                    </span>
                  ) : (
                    NO_DATA
                  )}
                </td>
                <td className="px-3 py-2">
                  {verdict ? (
                    <div className="space-y-1">
                      <span
                        className={cn(
                          chip,
                          verdict.approved ? statusTone('approved') : statusTone('rejected'),
                        )}
                      >
                        {verdict.approved ? COPY.verdictApprove : COPY.verdictReject} · {COPY.risk}{' '}
                        {verdict.risk_score}
                      </span>
                      <p className="line-clamp-2 text-muted-foreground">
                        {verdict.reasons.join(' · ')}
                      </p>
                    </div>
                  ) : (
                    <span className="text-muted-foreground">{COPY.pendingReview}</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    <span className={cn(chip, statusTone(status))}>{status}</span>
                    {proposal_grade && <Grade grade={proposal_grade.grade} />}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
