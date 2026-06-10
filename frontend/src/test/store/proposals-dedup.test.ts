import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useDashboardStore } from '@/stores/useDashboardStore'

// Regression coverage for the proposal-ingestion fix. The poller and the WS
// broadcast both deliver the SAME proposal repeatedly; addProposal must dedup
// on the backend id (so rows don't pile up), preserve the backend status (so
// approved/rejected don't read back as pending), and keep the backend id intact
// (so the approve/reject PATCH, which matches on trace_id, can find the row).
describe('addProposal dedup + status by backend id', () => {
  beforeEach(() => {
    useDashboardStore.setState({ proposals: [] })
  })
  afterEach(() => {
    useDashboardStore.setState({ proposals: [] })
  })

  const base = {
    proposal_type: 'parameter_change' as const,
    content: 'lower RSI threshold',
    requires_approval: true,
    timestamp: '2026-05-01T00:00:00.000Z',
  }

  it('upserts the same proposal id instead of duplicating it across polls', () => {
    const { addProposal } = useDashboardStore.getState()
    addProposal({ ...base, id: 'reflection_20260501T000000' })
    addProposal({ ...base, id: 'reflection_20260501T000000' })
    addProposal({ ...base, id: 'reflection_20260501T000000' })

    const list = useDashboardStore.getState().proposals
    expect(list).toHaveLength(1)
    expect(list[0].id).toBe('reflection_20260501T000000')
  })

  it('preserves the backend id verbatim so approve/reject can target it', () => {
    useDashboardStore.getState().addProposal({ ...base, id: 'trace-abc-123' })
    expect(useDashboardStore.getState().proposals[0].id).toBe('trace-abc-123')
  })

  it('reflects the backend status rather than forcing pending', () => {
    useDashboardStore.getState().addProposal({ ...base, id: 'p1', status: 'approved' })
    expect(useDashboardStore.getState().proposals[0].status).toBe('approved')
  })

  it('does not let a later pending poll clobber an optimistic approve/reject', () => {
    const { addProposal, updateProposalStatus } = useDashboardStore.getState()
    addProposal({ ...base, id: 'p1' }) // pending from first poll
    updateProposalStatus('p1', 'approved') // operator clicks approve
    addProposal({ ...base, id: 'p1', status: 'pending' }) // stale poll still says pending

    expect(useDashboardStore.getState().proposals[0].status).toBe('approved')
  })

  it('falls back to reflection_trace_id, then trace_id, then a generated id', () => {
    const { addProposal } = useDashboardStore.getState()
    addProposal({ ...base, reflection_trace_id: 'refl-1' })
    addProposal({ ...base, trace_id: 'tr-1' })
    addProposal({ ...base }) // no identifiers → generated id

    const list = useDashboardStore.getState().proposals
    expect(list).toHaveLength(3)
    expect(list.some((p) => p.id === 'refl-1')).toBe(true)
    expect(list.some((p) => p.id === 'tr-1')).toBe(true)
    expect(list.some((p) => /^\d+-/.test(p.id))).toBe(true)
  })

  it('keeps distinct proposals distinct (newest prepended)', () => {
    const { addProposal } = useDashboardStore.getState()
    addProposal({ ...base, id: 'older' })
    addProposal({ ...base, id: 'newer' })

    const ids = useDashboardStore.getState().proposals.map((p) => p.id)
    expect(ids).toEqual(['newer', 'older'])
  })
})
