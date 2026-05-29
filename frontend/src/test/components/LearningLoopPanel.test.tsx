import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import { agentDisplayName } from '@/constants/agents'

// The panel self-fetches via apiFetch — mock the client so we drive both
// endpoints (GET /dashboard/learning/loop and GET /dashboard/challengers).
vi.mock('@/lib/apiClient', () => ({
  API_ENDPOINTS: {
    LEARNING_LOOP: '/dashboard/learning/loop',
    DASHBOARD_CHALLENGERS: '/dashboard/challengers',
  },
  apiFetch: vi.fn(),
}))

import { apiFetch } from '@/lib/apiClient'
import { LearningLoopPanel } from '@/components/dashboard/LearningLoopPanel'

const mockApiFetch = apiFetch as unknown as ReturnType<typeof vi.fn>

const LOOP = {
  latest_grade: {
    trace_id: 't',
    grade: 'C',
    score_pct: 61.0,
    metrics: {},
    fills_graded: 5,
    timestamp: null,
  },
  recent_proposals: [
    {
      trace_id: 'p1',
      proposal_type: 'signal_weight_reduction',
      action: 'reduce_signal_weight',
      applied: true,
      applied_at: '2026-05-29T12:00:00Z',
      applied_by: 'PROPOSAL_APPLIER',
      message: 'signal_weight_scale 1.0000 -> 0.7000',
      timestamp: '2026-05-29T12:00:00Z',
    },
    {
      trace_id: 'p2',
      proposal_type: 'parameter_change',
      action: 'adjust_threshold',
      applied: false,
      applied_at: null,
      applied_by: null,
      message: null,
      timestamp: '2026-05-29T12:01:00Z',
    },
  ],
  loss_attribution: [],
  control_plane: {
    trading_paused: true,
    trading_paused_reason: 'grade F retirement proposal',
    signal_weight_scale: 0.49,
    suspended_agents: [{ agent_name: 'REASONING_AGENT', suspended_until: 1799999999 }],
  },
  timestamp: '2026-05-29T12:02:00Z',
}

const CHALLENGERS = {
  challengers: [{ challenger_id: 'abc123', fills: 12, max_fills: 200, running: true }],
}

describe('LearningLoopPanel', () => {
  beforeEach(() => {
    mockApiFetch.mockReset()
  })

  it('renders control plane, applied/pending split, suspended agents, and challengers', async () => {
    mockApiFetch.mockImplementation((path: string) => {
      if (path === '/dashboard/learning/loop') return Promise.resolve(LOOP)
      if (path === '/dashboard/challengers') return Promise.resolve(CHALLENGERS)
      return Promise.reject(new Error('unexpected path'))
    })

    render(<LearningLoopPanel />)

    // Control plane: paused state + dampened signal weight
    expect(await screen.findByText('PAUSED')).toBeInTheDocument()
    expect(screen.getByText('0.490')).toBeInTheDocument()

    // Proposals: both an applied and a pending row surface
    await waitFor(() => {
      expect(screen.getAllByText('applied').length).toBeGreaterThan(0)
      expect(screen.getAllByText('pending').length).toBeGreaterThan(0)
    })

    // Suspended agent chip rendered with the canonical display name
    expect(screen.getByText(agentDisplayName('REASONING_AGENT'))).toBeInTheDocument()

    // Challenger shadow with fills progress
    expect(screen.getByText(/challenger abc123/)).toBeInTheDocument()
    expect(screen.getByText('12/200 fills')).toBeInTheDocument()
  })

  it('degrades gracefully when both endpoints fail', async () => {
    mockApiFetch.mockRejectedValue(new Error('network'))

    render(<LearningLoopPanel />)

    // No crash; empty-state copy for proposals and challengers is shown.
    expect(await screen.findByText('No proposals yet.')).toBeInTheDocument()
    expect(screen.getByText('No shadow challengers running.')).toBeInTheDocument()
  })
})
