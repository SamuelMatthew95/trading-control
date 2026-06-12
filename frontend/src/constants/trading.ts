/**
 * Trading vocabulary constants — the wire values the backend emits for
 * proposal review states and order sides. Compare/assign through these,
 * never a raw string literal, so the contract has one home.
 */
import type { ProposalStatus } from '@/stores/types'

export const PROPOSAL_PENDING: ProposalStatus = 'pending'
export const PROPOSAL_APPROVED: ProposalStatus = 'approved'
export const PROPOSAL_REJECTED: ProposalStatus = 'rejected'

export const SIDE_BUY = 'buy'
export const SIDE_SELL = 'sell'
