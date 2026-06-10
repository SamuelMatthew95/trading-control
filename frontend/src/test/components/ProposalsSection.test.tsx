import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { ProposalsSection } from '@/components/dashboard/ProposalsSection'
import { useCodexStore, type Proposal } from '@/stores/useCodexStore'

function proposal(overrides: Partial<Proposal>): Proposal {
  return {
    id: 'p1',
    proposal_type: 'parameter_change',
    content: 'lower RSI threshold',
    requires_approval: true,
    timestamp: new Date().toISOString(),
    status: 'pending',
    ...overrides,
  }
}

describe('ProposalsSection', () => {
  beforeEach(() => {
    useCodexStore.setState({ proposals: [] })
  })

  it('shows the empty state when there are no proposals', () => {
    render(<ProposalsSection />)
    expect(screen.getByText(/No proposals yet/i)).toBeInTheDocument()
  })

  it('renders each proposal with its On-Approve routing badge', () => {
    useCodexStore.setState({
      proposals: [
        proposal({ id: 'p1', proposal_type: 'parameter_change', content: 'lower RSI' }),
        proposal({ id: 'p2', proposal_type: 'code_change', content: 'rewrite signal logic' }),
        proposal({ id: 'p3', proposal_type: 'tool_governance', content: 'disable dead tool' }),
      ],
    })
    const { container } = render(<ProposalsSection />)

    // Config-driven change is badged as an auto-PR; a code change as a GitHub issue.
    expect(container.textContent).toContain('Config auto-PR')
    expect(container.textContent).toContain('GitHub issue')
    expect(container.textContent).toContain('Tool registry')
    // The candidate-change content is shown.
    expect(screen.getByText('lower RSI')).toBeInTheDocument()
    // The On-Approve column header is present.
    expect(screen.getByText('On Approve')).toBeInTheDocument()
  })

  it('drills into a proposal: clicking the candidate change opens the detail modal', () => {
    useCodexStore.setState({
      proposals: [
        proposal({
          id: 'p9',
          proposal_type: 'challenger_promotion',
          content: "Promote 'mean_reversion' — beats baseline by +$2,121",
          trace_id: 'tr-9',
        }),
      ],
    })
    render(<ProposalsSection />)

    // Not open yet — the modal's "On approve" section heading is absent.
    expect(screen.queryByText('On approve')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Promote 'mean_reversion'/i }))

    // Modal opened: sections unique to the detail modal (not the table) are shown.
    // ("On approve" / "Evidence" are modal-only; the table header says "On Approve".)
    expect(screen.getByText('On approve')).toBeInTheDocument()
    expect(screen.getByText('Evidence')).toBeInTheDocument()
    // Full (un-truncated) trace id is rendered in the modal; the table truncates it.
    expect(screen.getByText('tr-9')).toBeInTheDocument()
  })
})
