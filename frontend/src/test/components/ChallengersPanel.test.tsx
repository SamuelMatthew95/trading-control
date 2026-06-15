import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

// The panel self-fetches via apiFetch — mock the client to drive
// GET /dashboard/challengers deterministically.
vi.mock('@/lib/apiClient', () => ({
  API_ENDPOINTS: {
    DASHBOARD_CHALLENGERS: '/dashboard/challengers',
  },
  apiFetch: vi.fn(),
}))

import { apiFetch } from '@/lib/apiClient'
import { ChallengersPanel } from '@/components/dashboard/ChallengersPanel'

const mockApiFetch = apiFetch as unknown as ReturnType<typeof vi.fn>

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
      baseline_shadow_trades: 6,
      baseline_shadow_win_rate: 0.5,
      baseline_shadow_pnl: 40.0,
      min_shadow_trades: 40,
      min_shadow_win_rate: 0.55,
      promotion_blockers: ['needs 32 more shadow trades'],
      ticks_observed: 5424,
      last_tick_at: new Date().toISOString(),
      open_shadow_positions: 1,
      recent_shadow_trades: [
        { symbol: 'SOL/USD', direction: 'long', pnl: 3.2, timestamp: new Date().toISOString() },
      ],
    },
  ],
}

describe('ChallengersPanel', () => {
  beforeEach(() => {
    mockApiFetch.mockReset()
  })

  it('shows each challenger with its full record and baseline comparison', async () => {
    mockApiFetch.mockResolvedValue(CHALLENGERS)
    render(<ChallengersPanel />)

    // Strategy identity + own shadow record.
    expect(await screen.findByText(/mean_reversion/)).toBeInTheDocument()
    expect(screen.getByText('Win rate')).toBeInTheDocument()
    expect(screen.getByText('63%')).toBeInTheDocument()
    expect(screen.getByText('1.21')).toBeInTheDocument() // sharpe
    // Baseline on the same ticks, with the ahead/behind verdict.
    expect(screen.getByText(/baseline on the same ticks: 6 trades/)).toBeInTheDocument()
    expect(screen.getByText(/challenger ahead/)).toBeInTheDocument()
    // Live trade flow.
    expect(screen.getByText(/long SOL\/USD/)).toBeInTheDocument()
  })

  it('names the unmet promotion requirements and shows trade progress', async () => {
    mockApiFetch.mockResolvedValue(CHALLENGERS)
    render(<ChallengersPanel />)

    // The harder bar is explicit: the exact unmet criterion is listed…
    expect(await screen.findByText(/needs 32 more shadow trades/)).toBeInTheDocument()
    // …with progress against the (raised) trade threshold.
    expect(screen.getByText('8/40')).toBeInTheDocument()
    expect(screen.getByText(/1 requirement unmet/)).toBeInTheDocument()
  })

  it('marks a challenger with no blockers as eligible', async () => {
    mockApiFetch.mockResolvedValue({
      challengers: [
        {
          ...CHALLENGERS.challengers[0],
          shadow_trades: 45,
          promotion_blockers: [],
        },
      ],
    })
    render(<ChallengersPanel />)
    expect(await screen.findByText('eligible')).toBeInTheDocument()
  })

  it('marks a graduated challenger from the backend status', async () => {
    mockApiFetch.mockResolvedValue({
      challengers: [
        {
          ...CHALLENGERS.challengers[0],
          graduated: true,
          learning_status: 'graduated',
        },
      ],
    })
    render(<ChallengersPanel />)
    expect(await screen.findByText('graduated')).toBeInTheDocument()
  })

  it('degrades gracefully when the endpoint fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('network'))
    render(<ChallengersPanel />)
    expect(await screen.findByText(/err: network/)).toBeInTheDocument()
    expect(screen.getByText(/No shadow challengers running/)).toBeInTheDocument()
  })
})
