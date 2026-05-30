import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

vi.mock('@/lib/apiClient', () => ({
  API_ENDPOINTS: { DASHBOARD_PROMPT_OS: '/dashboard/prompt-os' },
  apiFetch: vi.fn(),
}))

import { apiFetch } from '@/lib/apiClient'
import { LiveReasoningPanel } from '@/components/dashboard/LiveReasoningPanel'

const mockApiFetch = apiFetch as unknown as ReturnType<typeof vi.fn>

const PAYLOAD = {
  tool_count: 9,
  timestamp: '2026-05-30T00:00:00Z',
  champion: {
    node: 'reasoning',
    strategy_version: null,
    config: {},
    active_tools: [
      {
        name: 'get_ic_weights',
        phase: 'memory',
        enabled: true,
        alpha_score: 0.3,
        latency_ms: 8,
        failure_rate: 0,
        call_count: 4,
      },
    ],
    assembled_prompt: 'You are the Adaptive Trading System ... AVAILABLE TOOLS ... OUTPUT CONTRACT',
    constitution: 'You are the Adaptive Trading System operating under a fixed constitution.',
    output_contract: 'OUTPUT CONTRACT: Return ONLY a single valid JSON object',
  },
  challengers: [
    {
      challenger_id: 'abc123',
      fills: 50,
      max_fills: 200,
      running: true,
      variant: null,
      tool_overrides: null,
      config_diff: { grade_every: 5 },
      differs_by: 'config params',
    },
  ],
  proposals: [
    {
      id: 'p1',
      proposal_type: 'parameter_change',
      description: 'Lower RSI threshold to 28',
      confidence: 0.72,
      status: 'pending',
      applied: false,
    },
  ],
}

describe('LiveReasoningPanel', () => {
  beforeEach(() => {
    mockApiFetch.mockReset()
  })

  it('shows the live strategy, its active tools, challenger diff, and proposals', async () => {
    mockApiFetch.mockResolvedValue(PAYLOAD)
    const { container } = render(<LiveReasoningPanel />)

    // Wait for the data-dependent tool chip (the static header renders first).
    expect(await screen.findByText('get_ic_weights')).toBeInTheDocument()
    expect(screen.getByText('Live Reasoning')).toBeInTheDocument()
    // Challenger diff is surfaced (differs by + the config delta).
    expect(container.textContent).toContain('differs by config params')
    expect(container.textContent).toContain('grade_every=5')
    // Proposal content is shown.
    expect(screen.getByText('Lower RSI threshold to 28')).toBeInTheDocument()
  })

  it('reveals the assembled live prompt on demand', async () => {
    mockApiFetch.mockResolvedValue(PAYLOAD)
    render(<LiveReasoningPanel />)

    // Ensure the live data has loaded before toggling.
    await screen.findByText('get_ic_weights')
    fireEvent.click(screen.getByRole('button', { name: /view live prompt/i }))
    expect(screen.getByText(/AVAILABLE TOOLS/)).toBeInTheDocument()
  })

  it('degrades gracefully on fetch failure', async () => {
    mockApiFetch.mockRejectedValue(new Error('network'))
    render(<LiveReasoningPanel />)
    await waitFor(() => expect(screen.getByText(/err: network/)).toBeInTheDocument())
  })
})
