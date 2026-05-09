import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

/**
 * Regression test for Codex review #214 P1: proposal Approve/Reject must
 * call the backend vote endpoint BEFORE the local Zustand store is mutated.
 * If the API call fails, the store must NOT be updated (so a refresh can
 * resolve UI/server divergence).
 */

const { mockStore, mockUseCodexStore, voteOnProposalMock } = vi.hoisted(() => {
  const updateProposalStatus = vi.fn()
  const store: Record<string, unknown> = {
    wsConnected: true,
    killSwitchActive: false,
    setKillSwitch: vi.fn(),
    orders: [],
    positions: [],
    agentLogs: [],
    prices: {},
    systemMetrics: [],
    learningEvents: [],
    dashboardData: null,
    proposals: [
      {
        id: 'prop-1',
        proposal_type: 'parameter_change',
        content: 'Reduce ATR multiplier',
        requires_approval: true,
        timestamp: new Date().toISOString(),
        status: 'pending',
      },
    ],
    tradeFeed: [],
    agentInstances: [],
    performanceSummary: null,
    notifications: [],
    recentEvents: [],
    streamStats: {},
    agentStatuses: [],
    marketTickCount: 0,
    lastMarketSymbol: null,
    wsMessageCount: 0,
    wsLastMessageTimestamp: null,
    updateProposalStatus,
    setTradeFeed: vi.fn(),
    setAgentInstances: vi.fn(),
    setPerformanceSummary: vi.fn(),
    addProposal: vi.fn(),
    fetchPrices: vi.fn().mockResolvedValue(undefined),
    hydrateDashboard: vi.fn(),
  }
  const hook = Object.assign(
    (selector?: (s: typeof store) => unknown) =>
      typeof selector === 'function' ? selector(store) : store,
    { getState: () => store },
  )
  return {
    mockStore: store,
    mockUseCodexStore: hook,
    voteOnProposalMock: vi.fn(),
  }
})

vi.mock('@/stores/useCodexStore', () => ({
  useCodexStore: mockUseCodexStore,
}))

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api')
  return {
    ...actual,
    voteOnProposal: voteOnProposalMock,
  }
})

import { DashboardView } from '@/app/dashboard/DashboardView'

beforeAll(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({}),
  }) as unknown as typeof fetch
})

describe('Proposal vote persistence', () => {
  beforeEach(() => {
    voteOnProposalMock.mockReset()
    ;(mockStore.updateProposalStatus as ReturnType<typeof vi.fn>).mockReset()
  })

  it('persists Approve through voteOnProposal before updating local store', async () => {
    voteOnProposalMock.mockResolvedValueOnce({ ok: true })
    const user = userEvent.setup()

    render(<DashboardView section="learning" />)

    const approveButton = await screen.findByRole('button', { name: /approve/i })
    await user.click(approveButton)

    expect(voteOnProposalMock).toHaveBeenCalledTimes(1)
    expect(voteOnProposalMock).toHaveBeenCalledWith('prop-1', 'approved')
    expect(mockStore.updateProposalStatus).toHaveBeenCalledWith('prop-1', 'approved')

    // Order matters: API must succeed before the local mutation.
    const apiCallOrder = voteOnProposalMock.mock.invocationCallOrder[0]
    const storeCallOrder = (mockStore.updateProposalStatus as ReturnType<typeof vi.fn>).mock
      .invocationCallOrder[0]
    expect(apiCallOrder).toBeLessThan(storeCallOrder)
  })

  it('persists Reject through voteOnProposal', async () => {
    voteOnProposalMock.mockResolvedValueOnce({ ok: true })
    const user = userEvent.setup()

    render(<DashboardView section="learning" />)

    const rejectButton = await screen.findByRole('button', { name: /reject/i })
    await user.click(rejectButton)

    expect(voteOnProposalMock).toHaveBeenCalledWith('prop-1', 'rejected')
    expect(mockStore.updateProposalStatus).toHaveBeenCalledWith('prop-1', 'rejected')
  })

  it('does NOT update the local store when the API call fails', async () => {
    voteOnProposalMock.mockRejectedValueOnce(new Error('500 Internal Server Error'))
    const user = userEvent.setup()

    render(<DashboardView section="learning" />)

    const approveButton = await screen.findByRole('button', { name: /approve/i })
    await user.click(approveButton)

    expect(voteOnProposalMock).toHaveBeenCalledTimes(1)
    expect(mockStore.updateProposalStatus).not.toHaveBeenCalled()
  })

  it('disables vote buttons while a vote API call is in flight (no double-click race)', async () => {
    // Hold the API call open so we can observe the buttons mid-flight.
    let resolveVote: ((v: { ok: boolean }) => void) | null = null
    voteOnProposalMock.mockImplementationOnce(
      () =>
        new Promise<{ ok: boolean }>((resolve) => {
          resolveVote = resolve
        }),
    )

    const user = userEvent.setup()
    render(<DashboardView section="learning" />)

    const approveButton = await screen.findByRole('button', { name: /approve/i })
    const rejectButton = screen.getByRole('button', { name: /reject/i })

    await user.click(approveButton)

    // Both vote controls disable while the request is pending — operators
    // cannot fire a concurrent PATCH that races the first.
    const approveAfter = await screen.findByRole('button', { name: /working|approve/i })
    expect(approveAfter).toBeDisabled()
    expect(rejectButton).toBeDisabled()

    // Even attempting more clicks while pending must not enqueue more API calls.
    await user.click(approveAfter)
    await user.click(rejectButton)
    expect(voteOnProposalMock).toHaveBeenCalledTimes(1)

    // Resolving the call re-enables the buttons (until the proposal status
    // actually changes, but the test proposal remains pending in the mock store).
    resolveVote!({ ok: true })
  })
})
