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
  suggestions: [
    {
      tool: 'scan_sector_correlation',
      action: 'disable',
      severity: 'warning',
      reason: 'negative alpha (-0.20) — drop from the prompt',
    },
    {
      tool: 'calculate_vwap_execution',
      action: 'prioritize',
      severity: 'info',
      reason: 'highest alpha (+0.80) — keep at the top of the prompt',
    },
  ],
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
      success_count: 0,
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
      success_count: 12,
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
      success_count: 0,
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
    // Appears both as a phase-list row and in the suggestions block.
    expect(screen.getAllByText('scan_sector_correlation').length).toBeGreaterThan(0)
    // DAG phase headers.
    expect(screen.getByText('perception')).toBeInTheDocument()
    expect(screen.getByText('execution')).toBeInTheDocument()
    // Composite strings span multiple JSX text nodes — assert via full text.
    expect(container.textContent).toContain('2/3 enabled')
    expect(container.textContent).toContain('unlocks calculate_vwap_execution')
    expect(container.textContent).toContain('requires: risk_approved')
    expect(container.textContent).toContain('42ms')
  })

  it('distinguishes exercised tools from never-called tools with prior alpha', async () => {
    mockApiFetch.mockResolvedValue(REGISTRY)
    const { container } = render(<ToolGovernancePanel />)

    await screen.findByText('get_stream_confluence_metrics')
    // Never-called tools are flagged "unused" with a "prior" alpha tag…
    expect(container.textContent).toContain('unused')
    expect(container.textContent).toContain('prior')
    // …while an exercised tool shows its call/success ledger.
    expect(container.textContent).toContain('30× · 12 ok')
    // Header summarises live coverage (1 of 3 tools has been exercised).
    expect(container.textContent).toContain('1/3 exercised live')
  })

  it('frames recommendations as not-auto-applied, distinct from tool state', async () => {
    mockApiFetch.mockResolvedValue(REGISTRY)
    const { container } = render(<ToolGovernancePanel />)

    expect(await screen.findByText('Governance Recommendations')).toBeInTheDocument()
    // The recommendation badges are present…
    expect(container.textContent).toContain('disable')
    expect(container.textContent).toContain('prioritize')
    expect(container.textContent).toContain('negative alpha')
    // …but clearly framed as recommendations, not applied state.
    expect(container.textContent).toContain('nothing here is applied')
  })

  it('explains WHY each unused tool is unused (no mystery dead tools)', async () => {
    mockApiFetch.mockResolvedValue(REGISTRY)
    const { container } = render(<ToolGovernancePanel />)

    await screen.findByText('get_stream_confluence_metrics')
    // An execution-phase tool reads as downstream, not broken.
    expect(container.textContent).toContain('downstream tool')
    // A perception tool with no gate is simply not selected yet.
    expect(container.textContent).toContain('the reasoning LLM has not selected it yet')
  })

  it('degrades gracefully on fetch failure', async () => {
    mockApiFetch.mockRejectedValue(new Error('network'))
    render(<ToolGovernancePanel />)
    await waitFor(() => expect(screen.getByText('No tools registered.')).toBeInTheDocument())
  })
})
