import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import {
  BackendOfflineBanner,
  BackendOfflineEmptyState,
} from '@/components/dashboard/BackendOfflineBanner'
import { formatClockHMS } from '@/lib/formatters'

describe('BackendOfflineBanner', () => {
  it('shows the last-known-data time and stays alert-roled while active', () => {
    const iso = '2026-06-10T12:34:56Z'
    render(<BackendOfflineBanner active lastKnownAt={iso} />)
    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain('Backend unreachable')
    expect(alert.textContent).toContain(formatClockHMS(iso))
  })

  it('renders nothing while inactive', () => {
    render(<BackendOfflineBanner active={false} lastKnownAt={null} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('renders the placeholder clock when no sync ever happened', () => {
    render(<BackendOfflineBanner active lastKnownAt={null} />)
    expect(screen.getByRole('alert').textContent).toContain('--:--:--')
  })

  it('dismisses for the current outage and re-arms after recovery', () => {
    const { rerender } = render(<BackendOfflineBanner active lastKnownAt={null} />)
    fireEvent.click(screen.getByLabelText('Dismiss backend offline banner'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    // Still down — stays dismissed across re-renders of the same outage.
    rerender(<BackendOfflineBanner active lastKnownAt={null} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    // Recovery re-arms; the NEXT outage shows the banner again.
    rerender(<BackendOfflineBanner active={false} lastKnownAt={null} />)
    rerender(<BackendOfflineBanner active lastKnownAt={null} />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})

describe('BackendOfflineEmptyState', () => {
  it('explains the never-loaded case instead of showing blank panels', () => {
    render(<BackendOfflineEmptyState />)
    expect(screen.getByText('Backend offline — no data received yet')).toBeInTheDocument()
    expect(
      screen.getByText(/Panels will populate automatically/i),
    ).toBeInTheDocument()
  })
})

describe('formatClockHMS', () => {
  it('formats a valid ISO timestamp as HH:MM:SS', () => {
    // Match the component's locale-dependent output rather than a hard-coded
    // string so the test passes in any CI timezone/locale.
    const iso = '2026-06-10T12:34:56Z'
    const expected = new Date(iso).toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
    expect(formatClockHMS(iso)).toBe(expected)
  })

  it('returns the placeholder for null and garbage input', () => {
    expect(formatClockHMS(null)).toBe('--:--:--')
    expect(formatClockHMS('not-a-date')).toBe('--:--:--')
  })
})
