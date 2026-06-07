import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { NotificationFeed } from '@/components/dashboard/NotificationFeed'
import type { Notification } from '@/stores/useCodexStore'

const now = Date.now()
const minutesAgo = (m: number) => new Date(now - m * 60_000).toISOString()

function notif(partial: Partial<Notification> & Pick<Notification, 'id'>): Notification {
  return {
    severity: 'INFO',
    message: 'msg',
    notification_type: 'system.test',
    timestamp: minutesAgo(0),
    ...partial,
  }
}

describe('NotificationFeed live window', () => {
  it('hides notifications older than 1h so the feed reads live, not stale', () => {
    const notifications: Notification[] = [
      notif({ id: 'recent', title: 'Recent signal', timestamp: minutesAgo(5) }),
      notif({ id: 'stale', title: 'Old fill', timestamp: minutesAgo(3 * 60) }),
    ]
    render(<NotificationFeed notifications={notifications} wsConnected />)
    expect(screen.getByText('Recent signal')).toBeInTheDocument()
    // The 3-hour-old fill (persisted in Redis across restarts) is dropped.
    expect(screen.queryByText('Old fill')).toBeNull()
    // The count badge reflects only the live item.
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('shows a live-window empty state when every notification is stale', () => {
    const notifications: Notification[] = [
      notif({ id: 'stale', title: 'Old fill', timestamp: minutesAgo(3 * 60) }),
    ]
    render(<NotificationFeed notifications={notifications} wsConnected />)
    expect(screen.getByText('No notifications in the last hour')).toBeInTheDocument()
  })
})
