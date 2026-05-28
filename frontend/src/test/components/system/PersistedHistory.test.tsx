import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import { PersistedHistory } from '@/components/dashboard/system/PersistedHistory'
import type {
  PersistedHistoryItem,
  PersistedStreamCount,
} from '@/components/dashboard/system/types'

const FIXED_NOW = 1_780_000_000_000

const buildCount = (stream: string, count: number): PersistedStreamCount => ({
  stream,
  processed_count: count,
  last_processed_at: new Date(FIXED_NOW - 5_000).toISOString(),
})

const buildItem = (
  id: string,
  overrides: Partial<PersistedHistoryItem> = {},
): PersistedHistoryItem => ({
  id,
  kind: 'agent.signal',
  source: 'SIGNAL_AGENT',
  trace_id: 'trace-123',
  created_at: new Date(FIXED_NOW - 5_000).toISOString(),
  ...overrides,
})

const baseProps = {
  isInMemoryMode: false,
  persistedCounts: [] as PersistedStreamCount[],
  persistedEvents: [] as PersistedHistoryItem[],
  persistedLogs: [] as PersistedHistoryItem[],
  onSelectTrace: vi.fn(),
  now: () => FIXED_NOW,
}

describe('PersistedHistory', () => {
  it('shows a single memory-mode notice when in memory mode with no data', () => {
    render(<PersistedHistory {...baseProps} isInMemoryMode />)
    expect(screen.getByText(/running in memory mode/i)).toBeInTheDocument()
    // The redundant 3-panel layout is gone — no nested empty panels
    expect(screen.queryByText('Processed counts')).not.toBeInTheDocument()
    expect(screen.queryByText('Latest events')).not.toBeInTheDocument()
    expect(screen.queryByText('Latest agent logs')).not.toBeInTheDocument()
  })

  it('shows the persistence-disabled notice when not in memory mode and no data', () => {
    render(<PersistedHistory {...baseProps} />)
    expect(screen.getByText(/persistence not enabled/i)).toBeInTheDocument()
  })

  it('renders the 3-panel layout when there is any data', () => {
    render(
      <PersistedHistory
        {...baseProps}
        persistedCounts={[buildCount('signals', 1234), buildCount('orders', 5)]}
      />,
    )
    expect(screen.getByText('Processed counts')).toBeInTheDocument()
    expect(screen.getByText('Latest events')).toBeInTheDocument()
    expect(screen.getByText('Latest agent logs')).toBeInTheDocument()
    expect(screen.getByText('1,234')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('shows relative time on persisted events', () => {
    render(
      <PersistedHistory
        {...baseProps}
        persistedEvents={[buildItem('e-1', { kind: 'decision' })]}
      />,
    )
    expect(screen.getByText('decision')).toBeInTheDocument()
    expect(screen.getByText('5s ago')).toBeInTheDocument()
  })

  it('fires onSelectTrace when clicking an agent log row with trace_id', () => {
    const handler = vi.fn()
    render(
      <PersistedHistory
        {...baseProps}
        onSelectTrace={handler}
        persistedLogs={[
          buildItem('l-1', { kind: 'reasoning.log', trace_id: 'trace-xyz' }),
        ]}
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

  it('caps each panel list to 10 entries', () => {
    const many = Array.from({ length: 20 }, (_, i) =>
      buildItem(`x-${i}`, { kind: `k-${i}` }),
    )
    render(<PersistedHistory {...baseProps} persistedLogs={many} />)
    expect(screen.getByText('k-0')).toBeInTheDocument()
    expect(screen.getByText('k-9')).toBeInTheDocument()
    expect(screen.queryByText('k-10')).not.toBeInTheDocument()
  })

  it('renders data panels even in memory mode when the memory store has entries', () => {
    render(
      <PersistedHistory
        {...baseProps}
        isInMemoryMode
        persistedCounts={[buildCount('signals', 10)]}
      />,
    )
    expect(screen.queryByText(/running in memory mode/i)).not.toBeInTheDocument()
    expect(screen.getByText('Processed counts')).toBeInTheDocument()
  })
})
