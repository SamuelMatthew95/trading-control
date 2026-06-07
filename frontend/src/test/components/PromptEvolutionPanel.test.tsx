import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// The panel self-fetches via apiFetch — mock the client so we drive the payload.
vi.mock('@/lib/apiClient', () => ({
  API_ENDPOINTS: { DASHBOARD_PROMPT_EVOLUTION: '/dashboard/prompt-evolution' },
  apiFetch: vi.fn(),
}))

import { apiFetch } from '@/lib/apiClient'
import { PromptEvolutionPanel } from '@/components/dashboard/PromptEvolutionPanel'

const mockApiFetch = apiFetch as unknown as ReturnType<typeof vi.fn>

const PAYLOAD = {
  node: 'reasoning',
  active: {
    node: 'reasoning',
    text: "Promoted strategy 'mean_reversion': favor mean_reversion-aligned setups.",
    version: 3,
    rationale: 'operator-approved challenger promotion: mean_reversion',
    source: 'PROPOSAL_APPLIER',
    updated_at: '2026-06-07T12:00:00Z',
  },
  history: [
    {
      node: 'reasoning',
      text: 'Favor high-confluence longs; avoid news-spike entries.',
      version: 2,
      rationale: 'winning factor from reflection',
      source: 'reflection',
      updated_at: '2026-06-06T12:00:00Z',
    },
    {
      node: 'reasoning',
      text: 'Initial learned directive.',
      version: 1,
      rationale: '',
      source: 'reflection',
      updated_at: '2026-06-05T12:00:00Z',
    },
  ],
  version: 3,
  enabled: true,
  auto_apply: false,
}

describe('PromptEvolutionPanel', () => {
  beforeEach(() => {
    mockApiFetch.mockReset()
  })

  it('shows the current directive AND the full past history (versions, why, source)', async () => {
    mockApiFetch.mockResolvedValue(PAYLOAD)
    render(<PromptEvolutionPanel />)

    // Current (active) directive is visible with its version + provenance.
    await waitFor(() => {
      expect(
        screen.getByText(/favor mean_reversion-aligned setups/i),
      ).toBeInTheDocument()
    })
    expect(screen.getByText('v3')).toBeInTheDocument()
    // The promotion's provenance is visible — operator can see WHERE it came from.
    expect(screen.getAllByText('PROPOSAL_APPLIER').length).toBeGreaterThan(0)
    expect(
      screen.getByText(/operator-approved challenger promotion/i),
    ).toBeInTheDocument()

    // Past versions are all shown — not just the current one.
    expect(screen.getByText(/History · 2 prior versions/i)).toBeInTheDocument()
    expect(screen.getByText('v2')).toBeInTheDocument()
    expect(screen.getByText('v1')).toBeInTheDocument()
    expect(screen.getByText(/high-confluence longs/i)).toBeInTheDocument()
    expect(screen.getByText(/Initial learned directive/i)).toBeInTheDocument()
    // A prior version's rationale is shown too.
    expect(screen.getByText(/winning factor from reflection/i)).toBeInTheDocument()
  })

  it('renders the explanatory empty state when no directive exists yet', async () => {
    mockApiFetch.mockResolvedValue({ ...PAYLOAD, active: null, history: [] })
    render(<PromptEvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText(/No evolved directive yet/i)).toBeInTheDocument()
    })
  })
})
