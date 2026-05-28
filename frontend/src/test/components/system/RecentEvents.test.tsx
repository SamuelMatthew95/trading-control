import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { RecentEvents } from '@/components/dashboard/system/RecentEvents'

describe('RecentEvents', () => {
  it('shows empty state with disconnected message when WS off', () => {
    render(<RecentEvents events={[]} wsConnected={false} />)
    expect(screen.getByText(/stream disconnected/i)).toBeInTheDocument()
  })

  it('shows empty state with waiting message when WS on but no events', () => {
    render(<RecentEvents events={[]} wsConnected={true} />)
    expect(screen.getByText(/no websocket events yet/i)).toBeInTheDocument()
  })

  it('renders event stream badge, msgId and timestamp', () => {
    render(
      <RecentEvents
        wsConnected={true}
        events={[
          {
            stream: 'signals',
            msgId: '1234567890abcdef',
            timestamp: '2026-01-01T12:00:00Z',
          },
        ]}
      />,
    )
    expect(screen.getByText('signals')).toBeInTheDocument()
    expect(screen.getByText('1234567890abcdef')).toBeInTheDocument()
  })

  it('truncates very long msgIds', () => {
    render(
      <RecentEvents
        wsConnected={true}
        events={[
          {
            stream: 'orders',
            msgId: 'verylongmessageidentifier12345',
            timestamp: '2026-01-01T12:00:00Z',
          },
        ]}
      />,
    )
    // 16-char prefix shown
    expect(screen.getByText('verylongmessagei')).toBeInTheDocument()
  })

  it('shows dash for "n/a" msgId', () => {
    render(
      <RecentEvents
        wsConnected={true}
        events={[{ stream: 'signals', msgId: 'n/a', timestamp: '2026-01-01T12:00:00Z' }]}
      />,
    )
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('caps displayed events at 15', () => {
    const events = Array.from({ length: 25 }, (_, i) => ({
      stream: 'signals',
      msgId: `msg-${i}`,
      timestamp: '2026-01-01T12:00:00Z',
    }))
    render(<RecentEvents wsConnected={true} events={events} />)
    expect(screen.getByText('msg-0')).toBeInTheDocument()
    expect(screen.getByText('msg-14')).toBeInTheDocument()
    expect(screen.queryByText('msg-15')).not.toBeInTheDocument()
  })

  it('handles null stream gracefully', () => {
    render(
      <RecentEvents
        wsConnected={true}
        events={[{ stream: null, msgId: 'abc', timestamp: '2026-01-01T12:00:00Z' }]}
      />,
    )
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })
})
