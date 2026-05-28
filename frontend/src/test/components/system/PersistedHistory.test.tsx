import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import { PersistedHistory } from '@/components/dashboard/system/PersistedHistory'
import type {
  PersistedHistoryItem,
  PersistedStreamCount,
} from '@/components/dashboard/system/types'

const buildCount = (stream: string, count: number): PersistedStreamCount => ({
  stream,
  processed_count: count,
  last_processed_at: '2026-01-01T12:00:00Z',
})

const buildItem = (id: string, overrides: Partial<PersistedHistoryItem> = {}): PersistedHistoryItem => ({
  id,
  kind: 'agent.signal',
  source: 'SIGNAL_AGENT',
  trace_id: 'trace-123',
  created_at: '2026-01-01T12:00:00Z',
  ...overrides,
})

const baseProps = {
  isInMemoryMode: false,
  persistedCounts: [] as PersistedStreamCount[],
  persistedEvents: [] as PersistedHistoryItem[],
  persistedLogs: [] as PersistedHistoryItem[],
  onSelectTrace: vi.fn(),
}

describe('PersistedHistory', () => {
  it('shows three empty panels with "Persistence not enabled" by default', () => {
    render(<PersistedHistory {...baseProps} />)
    expect(screen.getAllByText(/persistence not enabled/i)).toHaveLength(3)
  })

  it('shows in-memory mode message when isInMemoryMode is true', () => {
    render(<PersistedHistory {...baseProps} isInMemoryMode />)
    expect(screen.getAllByText(/in-memory mode \(no db persistence\)/i)).toHaveLength(3)
  })

  it('renders stream counts when provided', () => {
    render(
      <PersistedHistory
        {...baseProps}
        persistedCounts={[buildCount('signals', 1234), buildCount('orders', 5)]}
      />,
    )
    expect(screen.getByText('1,234')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('renders event kinds in latest events panel', () => {
    render(
      <PersistedHistory
        {...baseProps}
        persistedEvents={[buildItem('e-1', { kind: 'decision' })]}
      />,
    )
    expect(screen.getByText('decision')).toBeInTheDocument()
  })

  it('renders agent log buttons that fire onSelectTrace', () => {
    const handler = vi.fn()
    render(
      <PersistedHistory
        {...baseProps}
        onSelectTrace={handler}
        persistedLogs={[buildItem('l-1', { kind: 'reasoning.log', trace_id: 'trace-xyz' })]}
      />,
    )
    const btn = screen.getByRole('button', { name: /reasoning.log/i })
    fireEvent.click(btn)
    expect(handler).toHaveBeenCalledWith('trace-xyz')
  })

  it('disables the agent log button when trace_id is missing', () => {
    render(
      <PersistedHistory
        {...baseProps}
        persistedLogs={[buildItem('l-1', { trace_id: null })]}
      />,
    )
    expect(screen.getByRole('button')).toBeDisabled()
  })

  it('caps each list to 10 entries', () => {
    const many = Array.from({ length: 20 }, (_, i) => buildItem(`x-${i}`, { kind: `k-${i}` }))
    render(<PersistedHistory {...baseProps} persistedLogs={many} />)
    expect(screen.getByText('k-0')).toBeInTheDocument()
    expect(screen.getByText('k-9')).toBeInTheDocument()
    expect(screen.queryByText('k-10')).not.toBeInTheDocument()
  })
})
