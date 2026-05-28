import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { RecentEvents } from '@/components/dashboard/system/RecentEvents'

const FIXED_NOW = 1_780_000_000_000

describe('RecentEvents', () => {
  it('shows empty state with disconnected message when WS off', () => {
    render(<RecentEvents events={[]} wsConnected={false} />)
    expect(screen.getByText(/stream disconnected/i)).toBeInTheDocument()
  })

  it('shows empty state with waiting message when WS on but no events', () => {
    render(<RecentEvents events={[]} wsConnected={true} />)
    expect(screen.getByText(/no websocket events yet/i)).toBeInTheDocument()
  })

  it('renders the stream badge and relative time for each event', () => {
    render(
      <RecentEvents
        wsConnected={true}
        now={() => FIXED_NOW}
        events={[
          {
            stream: 'signals',
            msgId: '1234567890abcdef',
            timestamp: new Date(FIXED_NOW - 3_000).toISOString(),
          },
        ]}
      />,
    )
    expect(screen.getAllByText('signals').length).toBeGreaterThan(0)
    expect(screen.getByText('3s ago')).toBeInTheDocument()
  })

  it('renders a stream summary header with counts', () => {
    render(
      <RecentEvents
        wsConnected={true}
        now={() => FIXED_NOW}
        events={[
          { stream: 'signals', msgId: 'a', timestamp: new Date(FIXED_NOW - 1_000).toISOString() },
          { stream: 'signals', msgId: 'b', timestamp: new Date(FIXED_NOW - 2_000).toISOString() },
          {
            stream: 'market_events',
            msgId: 'c',
            timestamp: new Date(FIXED_NOW - 3_000).toISOString(),
          },
        ]}
      />,
    )
    // Summary header should show counts: signals 2, market_events 1
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('no longer renders the msgId column in rows', () => {
    render(
      <RecentEvents
        wsConnected={true}
        now={() => FIXED_NOW}
        events={[
          {
            stream: 'orders',
            msgId: 'verylongmessageidentifier12345',
            timestamp: new Date(FIXED_NOW - 5_000).toISOString(),
          },
        ]}
      />,
    )
    expect(screen.queryByText(/verylongmessagei/)).not.toBeInTheDocument()
  })

  it('shows "just now" for events less than a second old', () => {
    render(
      <RecentEvents
        wsConnected={true}
        now={() => FIXED_NOW}
        events={[
          {
            stream: 'signals',
            msgId: 'a',
            timestamp: new Date(FIXED_NOW - 200).toISOString(),
          },
        ]}
      />,
    )
    expect(screen.getByText('just now')).toBeInTheDocument()
  })

  it('caps displayed events at 15', () => {
    const events = Array.from({ length: 25 }, (_, i) => ({
      stream: 'signals',
      msgId: `msg-${i}`,
      timestamp: new Date(FIXED_NOW - i * 1_000).toISOString(),
    }))
    render(<RecentEvents wsConnected={true} events={events} now={() => FIXED_NOW} />)
    // Summary chip shows truncated 15-count
    expect(screen.getAllByText('15').length).toBeGreaterThan(0)
  })

  it('handles null stream gracefully', () => {
    render(
      <RecentEvents
        wsConnected={true}
        now={() => FIXED_NOW}
        events={[
          { stream: null, msgId: 'abc', timestamp: new Date(FIXED_NOW - 1_000).toISOString() },
        ]}
      />,
    )
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })
})
