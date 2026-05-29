import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

vi.mock('@/lib/apiClient', () => ({
  API_ENDPOINTS: { DASHBOARD_TOOLS: '/dashboard/tools' },
  apiFetch: vi.fn(),
}))

import { apiFetch } from '@/lib/apiClient'
import { ToolGovernancePanel } from '@/components/dashboard/ToolGovernancePanel'

const mockApiFetch = apiFetch as unknown as ReturnType<typeof vi.fn>

const REGISTRY = {
  count: 3,
  capability_graph: { get_stream_confluence_metrics: ['calculate_vwap_execution'] },
  tools: [
    {
      name: 'get_stream_confluence_metrics',
      phase: 'perception',
      description: '',
      enabled: true,
      alpha_score: 0.6,
      latency_ms: 42,
      failure_rate: 0,
      call_count: 0,
      required_state_flags: [],
      unlocks: ['calculate_vwap_execution'],
    },
    {
      name: 'scan_sector_correlation',
      phase: 'perception',
      description: '',
      enabled: false,
      alpha_score: -0.2,
      latency_ms: 120,
      failure_rate: 0.6,
      call_count: 30,
      required_state_flags: ['confluence_loaded'],
      unlocks: [],
    },
    {
      name: 'calculate_vwap_execution',
      phase: 'execution',
      description: '',
      enabled: true,
      alpha_score: 0.8,
      latency_ms: 30,
      failure_rate: 0,
      call_count: 0,
      required_state_flags: ['risk_approved'],
      unlocks: [],
    },
  ],
}

describe('ToolGovernancePanel', () => {
  beforeEach(() => {
    mockApiFetch.mockReset()
  })

  it('groups tools by DAG phase and shows attribution, gating, and unlocks', async () => {
    mockApiFetch.mockResolvedValue(REGISTRY)
    const { container } = render(<ToolGovernancePanel />)

    // Gate on data-dependent content (a tool name only appears after the fetch).
    expect(await screen.findByText('get_stream_confluence_metrics')).toBeInTheDocument()
    expect(screen.getByText(/Tool Governance/)).toBeInTheDocument()
    expect(screen.getByText('scan_sector_correlation')).toBeInTheDocument()
    // DAG phase headers.
    expect(screen.getByText('perception')).toBeInTheDocument()
    expect(screen.getByText('execution')).toBeInTheDocument()
    // Composite strings span multiple JSX text nodes — assert via full text.
    expect(container.textContent).toContain('2/3 enabled')
    expect(container.textContent).toContain('unlocks calculate_vwap_execution')
    expect(container.textContent).toContain('requires: risk_approved')
    expect(container.textContent).toContain('42ms')
  })

  it('degrades gracefully on fetch failure', async () => {
    mockApiFetch.mockRejectedValue(new Error('network'))
    render(<ToolGovernancePanel />)
    await waitFor(() => expect(screen.getByText('No tools registered.')).toBeInTheDocument())
  })
})
