import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { HeroMetrics } from '@/components/dashboard/system/HeroMetrics'
import type { ApiHealth, WsDiagnosticsLike } from '@/components/dashboard/system/types'

const wsDiagnostics: WsDiagnosticsLike = {
  reconnectAttempts: 0,
  messageRate: 2.5,
  lastError: null,
}

const apiHealth: ApiHealth = {
  dashboardState: 'ok',
  agentInstances: 'ok',
  eventHistory: 'ok',
}

const baseProps = {
  pipelineStatus: 'Healthy' as const,
  marketStageCount: 1234,
  effectiveLatencyMs: 250,
  throughput: 2.5,
  wsConnected: true,
  wsMessageCount: 100,
  wsDiagnostics,
  isInMemoryMode: false,
  apiHealth,
  llmAvailable: true as boolean | null,
  llmProvider: 'openai',
}

describe('HeroMetrics', () => {
  it('renders all six metrics', () => {
    render(<HeroMetrics {...baseProps} />)
    expect(screen.getByRole('group', { name: /pipeline/i })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /data latency/i })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /throughput/i })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /websocket/i })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /database/i })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /llm/i })).toBeInTheDocument()
  })

  it('shows memory mode for DB when isInMemoryMode is true', () => {
    render(<HeroMetrics {...baseProps} isInMemoryMode />)
    expect(screen.getByText('Memory')).toBeInTheDocument()
    expect(screen.getByText('no persistence')).toBeInTheDocument()
  })

  it('shows rule-based when llmAvailable=false', () => {
    render(<HeroMetrics {...baseProps} llmAvailable={false} />)
    expect(screen.getByText('Rule-Based')).toBeInTheDocument()
  })

  it('shows AI-Powered when llmAvailable=true', () => {
    render(<HeroMetrics {...baseProps} llmAvailable={true} />)
    expect(screen.getByText('AI-Powered')).toBeInTheDocument()
  })

  it('shows -- for latency when effectiveLatencyMs is null', () => {
    render(<HeroMetrics {...baseProps} effectiveLatencyMs={null} />)
    expect(screen.getByText('--')).toBeInTheDocument()
    expect(screen.getByText('no recent activity')).toBeInTheDocument()
  })

  it('shows Disconnected when wsConnected=false', () => {
    render(<HeroMetrics {...baseProps} wsConnected={false} />)
    expect(screen.getByText('Disconnected')).toBeInTheDocument()
  })

  it('shows Pending DB state for pending api health', () => {
    render(
      <HeroMetrics {...baseProps} apiHealth={{ ...apiHealth, dashboardState: 'pending' }} />,
    )
    expect(screen.getByText('Pending')).toBeInTheDocument()
  })

  it('shows Error DB state when dashboard health errors', () => {
    render(<HeroMetrics {...baseProps} apiHealth={{ ...apiHealth, dashboardState: 'error' }} />)
    expect(screen.getByText('Error')).toBeInTheDocument()
  })

  it('formats throughput to 2 decimals with /s suffix', () => {
    render(<HeroMetrics {...baseProps} throughput={3.14159} />)
    expect(screen.getByText('3.14/s')).toBeInTheDocument()
  })
})
