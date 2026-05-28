import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { StreamActivity } from '@/components/dashboard/system/StreamActivity'

const FIXED_NOW = 1_780_000_000_000

describe('StreamActivity', () => {
  it('renders all eight system streams', () => {
    render(<StreamActivity streamStats={{}} now={() => FIXED_NOW} />)
    for (const stream of [
      'market_ticks',
      'market_events',
      'signals',
      'orders',
      'executions',
      'agent_logs',
      'risk_alerts',
      'notifications',
    ]) {
      expect(screen.getByText(stream)).toBeInTheDocument()
    }
  })

  it('shows 0 count and slate dot when no data', () => {
    const { container } = render(<StreamActivity streamStats={{}} now={() => FIXED_NOW} />)
    // First entry's count should be 0
    const counts = screen.getAllByText('0')
    expect(counts.length).toBeGreaterThan(0)
    expect(container.querySelector('.bg-slate-400')).toBeTruthy()
  })

  it('shows amber dot when count > 0 but stale', () => {
    const { container } = render(
      <StreamActivity
        streamStats={{
          signals: {
            count: 5,
            lastMessageTimestamp: new Date(FIXED_NOW - 120_000).toISOString(),
          },
        }}
        now={() => FIXED_NOW}
      />,
    )
    expect(container.querySelector('.bg-amber-400')).toBeTruthy()
  })

  it('shows emerald pulsing dot when live (within freshness window)', () => {
    const { container } = render(
      <StreamActivity
        streamStats={{
          signals: {
            count: 5,
            lastMessageTimestamp: new Date(FIXED_NOW - 1_000).toISOString(),
          },
        }}
        now={() => FIXED_NOW}
      />,
    )
    expect(container.querySelector('.animate-pulse.bg-emerald-500')).toBeTruthy()
  })

  it('formats counts with locale separators', () => {
    render(
      <StreamActivity
        streamStats={{
          market_ticks: { count: 12345, lastMessageTimestamp: null },
        }}
        now={() => FIXED_NOW}
      />,
    )
    expect(screen.getByText('12,345')).toBeInTheDocument()
  })
})
