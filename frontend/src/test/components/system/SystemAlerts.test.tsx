import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { SystemAlerts } from '@/components/dashboard/system/SystemAlerts'

const baseProps = {
  pipelineWarning: false,
  hasMarketData: true,
  latestMarketTickTs: '2026-01-01T00:00:00Z',
  systemFeedError: null,
  persistenceEnabled: true,
  llmAvailable: true as boolean | null,
  llmProvider: 'openai',
}

describe('SystemAlerts', () => {
  it('renders nothing when everything is healthy', () => {
    const { container } = render(<SystemAlerts {...baseProps} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows pipeline warning when signals > 0 but orders == 0', () => {
    render(<SystemAlerts {...baseProps} pipelineWarning />)
    expect(screen.getByText(/signals generated but no orders/i)).toBeInTheDocument()
  })

  it('shows no market data error when feed is empty', () => {
    render(<SystemAlerts {...baseProps} hasMarketData={false} latestMarketTickTs={null} />)
    expect(screen.getByText(/no market data received/i)).toBeInTheDocument()
  })

  it('shows market_ticks missing warning when market_events present without market_ticks', () => {
    render(<SystemAlerts {...baseProps} latestMarketTickTs={null} />)
    expect(screen.getByText(/market events arriving, market_ticks missing/i)).toBeInTheDocument()
  })

  it('shows systemFeedError when present', () => {
    render(<SystemAlerts {...baseProps} systemFeedError="API unreachable" />)
    expect(screen.getByText(/api unreachable/i)).toBeInTheDocument()
  })

  it('shows persistence disabled banner when persistence is off', () => {
    render(<SystemAlerts {...baseProps} persistenceEnabled={false} />)
    expect(screen.getByText(/persistence disabled/i)).toBeInTheDocument()
  })

  it('shows rule-based mode info when llmAvailable is false', () => {
    render(<SystemAlerts {...baseProps} llmAvailable={false} llmProvider="anthropic" />)
    expect(screen.getByText(/rule-based reasoning mode/i)).toBeInTheDocument()
    expect(screen.getByText(/ANTHROPIC_API_KEY/)).toBeInTheDocument()
  })

  it('falls back to "an LLM API key" when no provider given', () => {
    render(<SystemAlerts {...baseProps} llmAvailable={false} llmProvider="" />)
    expect(screen.getByText(/set an LLM API key/i)).toBeInTheDocument()
  })

  it('renders multiple alerts at once when multiple conditions trip', () => {
    render(
      <SystemAlerts
        {...baseProps}
        pipelineWarning
        persistenceEnabled={false}
        systemFeedError="WS lost"
      />,
    )
    expect(screen.getAllByRole('alert')).toHaveLength(3)
  })
})
