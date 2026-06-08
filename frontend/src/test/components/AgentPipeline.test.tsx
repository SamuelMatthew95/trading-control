import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { AgentPipeline } from '@/components/dashboard/AgentPipeline'
import type { AgentPipelineInput } from '@/lib/agent-pipeline'
import { AGENT_REASONING, AGENT_SIGNAL } from '@/constants/agents'

const baseProps: AgentPipelineInput = {
  agents: [],
  marketTickCount: 0,
  lastMarketSymbol: null,
  marketLive: false,
  decisionStats: null,
  proposalsCount: 0,
}

describe('AgentPipeline', () => {
  it('renders every stage label and the canonical agent display names', () => {
    render(<AgentPipeline {...baseProps} />)
    for (const label of ['Market', 'Signal', 'Reasoning', 'Execution', 'Grade', 'IC Update', 'Reflection', 'Proposer']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    // Names match the Agent Status table (agentDisplayName), not class-style names.
    expect(screen.getByText('Signal Agent')).toBeInTheDocument()
    expect(screen.getByText('Reasoning Agent')).toBeInTheDocument()
    expect(screen.getByText('Strategy Proposer')).toBeInTheDocument()
    expect(screen.queryByText('SignalGenerator')).not.toBeInTheDocument()
  })

  it('shows reporting agents as Live and missing agents as Waiting', () => {
    render(
      <AgentPipeline
        {...baseProps}
        agents={[{ name: AGENT_SIGNAL, status: 'Live', eventCount: 12, lastSeen: new Date() }]}
        marketLive
        marketTickCount={60}
      />,
    )
    expect(screen.getAllByText('Live').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Waiting').length).toBeGreaterThan(0)
    expect(screen.getByText('12')).toBeInTheDocument()
  })

  it('renders a decision breakdown fact when decision stats are present', () => {
    render(
      <AgentPipeline
        {...baseProps}
        agents={[{ name: AGENT_REASONING, status: 'Live', eventCount: 3, lastSeen: new Date() }]}
        decisionStats={{ total: 8, last_hour: { buys: 4, sells: 3, holds: 1 } }}
      />,
    )
    expect(screen.getByText('4 buy · 3 sell')).toBeInTheDocument()
  })

  it('never renders NaN, even with a partial decisionStats object', () => {
    render(<AgentPipeline {...baseProps} decisionStats={{}} />)
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
  })
})
