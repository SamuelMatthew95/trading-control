import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('@/lib/apiClient', () => ({
  API_ENDPOINTS: { AGENTS_PERFORMANCE: '/dashboard/agents/performance' },
  apiFetch: vi.fn(),
  api: (path: string) => path,
}))

import { apiFetch } from '@/lib/apiClient'
import { AgentScorecards } from '@/components/dashboard/agents/AgentScorecards'

const mockApiFetch = apiFetch as unknown as ReturnType<typeof vi.fn>

const PAYLOAD = {
  promoted: 1,
  mode: 'memory',
  timestamp: '',
  agents: [
    {
      name: 'SIGNAL_AGENT',
      display_name: 'Signal Agent',
      status: 'ACTIVE',
      grade: 'A',
      score: 0.92,
      score_pct: 92,
      tier: 'PROMOTED',
      promoted: true,
      event_count: 30,
      total_runs: 5,
      completed_runs: 5,
      failed_runs: 0,
      dimensions: [{ key: 'liveness', label: 'Liveness', value: 1, weight: 0.4, data_available: true }],
      learnings: [],
    },
    {
      name: 'REASONING_AGENT',
      display_name: 'Reasoning Agent',
      status: 'INSUFFICIENT_DATA',
      grade: null,
      score: null,
      score_pct: null,
      tier: 'UNRATED',
      promoted: false,
      event_count: 0,
      total_runs: 0,
      completed_runs: 0,
      failed_runs: 0,
      dimensions: [{ key: 'liveness', label: 'Liveness', value: 0, weight: 0.4, data_available: false }],
      learnings: [],
    },
  ],
}

describe('AgentScorecards', () => {
  beforeEach(() => {
    mockApiFetch.mockReset()
    mockApiFetch.mockResolvedValue(PAYLOAD)
  })

  it('renders a card per agent with grade, tier, and the promoted count', async () => {
    render(<AgentScorecards />)

    expect(await screen.findByText('Signal Agent')).toBeInTheDocument()
    expect(screen.getByText('Reasoning Agent')).toBeInTheDocument()
    expect(screen.getByText('1 promoted')).toBeInTheDocument()
    // Promoted agent shows its tier label + score; unrated agent reads "unrated".
    expect(screen.getByText('Promoted')).toBeInTheDocument()
    expect(screen.getByText('Unrated')).toBeInTheDocument()
    expect(screen.getByText('92%')).toBeInTheDocument()
    // The unrated agent's score reads "unrated" (also appears in the explainer copy).
    expect(screen.getAllByText('unrated').length).toBeGreaterThan(0)
  })
})
