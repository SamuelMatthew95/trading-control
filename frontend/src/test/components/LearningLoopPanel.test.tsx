import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import { agentDisplayName } from '@/constants/agents'

// The panel self-fetches via apiFetch — mock the client so we drive both
// endpoints (GET /dashboard/learning/loop and GET /dashboard/challengers).
vi.mock('@/lib/apiClient', () => ({
  API_ENDPOINTS: {
    LEARNING_LOOP: '/dashboard/learning/loop',
    DASHBOARD_CHALLENGERS: '/dashboard/challengers',
    LEARNING_PENDING_PARAM_CHANGES: '/learning/pending-param-changes',
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
  challengers: [
    {
      challenger_id: 'abc123',
      fills: 12,
      max_fills: 200,
      running: true,
      strategy: 'mean_reversion',
      shadow_trades: 8,
      shadow_win_rate: 0.625,
      shadow_pnl: 142.5,
      shadow_sharpe: 1.21,
      beats_baseline_shadow: true,
      // Full-visibility fields: promotion progress + liveness + trade flow.
      min_shadow_trades: 25,
      ticks_observed: 5424,
      last_tick_at: new Date().toISOString(),
      open_shadow_positions: 1,
      recent_shadow_trades: [
        { symbol: 'SOL/USD', direction: 'long', pnl: 3.2, timestamp: new Date().toISOString() },
      ],
    },
  ],
}

const PENDING_PRS = {
  items: [
    {
      parameter: 'SIGNAL_CONFIDENCE_MIN_GATE',
      previous_value: 0.65,
      proposed_value: 0.55,
      reason: 'too many momentum signals gated',
      timestamp: '2026-05-29T12:03:00Z',
    },
  ],
}

describe('LearningLoopPanel', () => {
  beforeEach(() => {
    mockApiFetch.mockReset()
  })

  const _wireAll = () => {
    mockApiFetch.mockImplementation((path: string) => {
      if (path === '/dashboard/learning/loop') return Promise.resolve(LOOP)
      if (path === '/dashboard/challengers') return Promise.resolve(CHALLENGERS)
      if (path === '/learning/pending-param-changes') return Promise.resolve(PENDING_PRS)
      return Promise.reject(new Error('unexpected path'))
    })
  }

  it('renders control plane, applied/pending split, suspended agents, and challengers', async () => {
    _wireAll()

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
  })

  it('summarizes challengers and links to the dedicated page', async () => {
    // The full evidence trail moved to /dashboard/challengers — this panel only
    // carries the headline count and a link (ChallengersPanel.test.tsx covers
    // the detailed view).
    _wireAll()
    render(<LearningLoopPanel />)

    expect(
      await screen.findByText(/1 running · 1 beating baseline · 0 promotions proposed/),
    ).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /follow challengers/i })
    expect(link).toHaveAttribute('href', '/dashboard/challengers')
  })

  it('lists pending parameter-change PRs (GitOps loop)', async () => {
    _wireAll()
    render(<LearningLoopPanel />)

    expect(await screen.findByText('SIGNAL_CONFIDENCE_MIN_GATE')).toBeInTheDocument()
    expect(screen.getByText('0.55')).toBeInTheDocument() // proposed value
    expect(screen.getByText(/too many momentum signals gated/)).toBeInTheDocument()
  })

  it('degrades gracefully when all endpoints fail', async () => {
    mockApiFetch.mockRejectedValue(new Error('network'))

    render(<LearningLoopPanel />)

    // No crash; empty-state copy for each section is shown.
    expect(await screen.findByText('No proposals yet.')).toBeInTheDocument()
    expect(screen.getByText('No shadow challengers running.')).toBeInTheDocument()
    expect(
      screen.getByText(/No pending parameter changes/),
    ).toBeInTheDocument()
  })
})
