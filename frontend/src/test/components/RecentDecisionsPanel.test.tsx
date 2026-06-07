import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { RecentDecisionsPanel } from '@/components/dashboard/RecentDecisionsPanel'
import type { DecisionStats } from '@/hooks/useRestPoll'

// Mirrors the confusing real-world reading from the dashboard: 14 holds in the
// last hour sitting next to an all-time list pinned at its 500 cap. 0 + 0 + 14
// != 500 because the two figures are *different time windows* — the panel must
// label them so they can't be read as one running total.
const STATS: DecisionStats = {
  total: 500,
  last_hour: { buys: 0, sells: 0, holds: 14 },
  last_decision: null,
}

describe('RecentDecisionsPanel', () => {
  it('labels the last-hour breakdown and the all-time total as distinct windows', () => {
    render(<RecentDecisionsPanel stats={STATS} recent={[]} />)

    // The fix: explicit window labels so buys/sells/holds (last hour) can't be
    // mistaken for a running tally against the all-time count.
    expect(screen.getByText('last 1h')).toBeInTheDocument()
    expect(screen.getByText('all-time')).toBeInTheDocument()

    // Last-hour figures.
    expect(screen.getByText(/Buys:\s*0/)).toBeInTheDocument()
    expect(screen.getByText(/Sells:\s*0/)).toBeInTheDocument()
    expect(screen.getByText(/Holds:\s*14/)).toBeInTheDocument()

    // All-time capped total — deliberately not equal to buys + sells + holds.
    expect(screen.getByText(/Total:\s*500/)).toBeInTheDocument()
  })

  it('shows only buy/sell rows in the recent list and filters out holds', () => {
    const recent = [
      {
        id: '1',
        action: 'buy',
        symbol: 'BTC/USD',
        price: 43000,
        confidence: 0.8,
        timestamp: '2026-05-30T12:00:00Z',
      },
      {
        id: '2',
        action: 'hold',
        symbol: 'ETH/USD',
        price: 2400,
        confidence: 0.5,
        timestamp: '2026-05-30T12:01:00Z',
      },
    ]
    render(<RecentDecisionsPanel stats={STATS} recent={recent} />)

    expect(screen.getByText('BTC/USD')).toBeInTheDocument()
    // Hold rows are not actionable and stay out of the list.
    expect(screen.queryByText('ETH/USD')).not.toBeInTheDocument()
  })

  it('renders the empty state when there are no actionable decisions', () => {
    render(<RecentDecisionsPanel stats={null} recent={[]} />)
    expect(screen.getByText('No buy/sell decisions yet')).toBeInTheDocument()
  })

  it('drills into a decision trace when wired and the decision has a trace_id', () => {
    const onSelectTrace = vi.fn()
    const recent = [
      {
        id: '1',
        trace_id: 'trace-abc',
        action: 'buy',
        symbol: 'BTC/USD',
        price: 43000,
        confidence: 0.8,
        timestamp: '2026-05-30T12:00:00Z',
      },
    ]
    render(<RecentDecisionsPanel stats={STATS} recent={recent} onSelectTrace={onSelectTrace} />)
    fireEvent.click(screen.getByRole('button', { name: /trace/i }))
    expect(onSelectTrace).toHaveBeenCalledWith('trace-abc')
  })

  it('shows no trace button when the decision lacks a trace_id', () => {
    const recent = [
      { id: '1', action: 'buy', symbol: 'BTC/USD', price: 43000, confidence: 0.8, timestamp: null },
    ]
    render(<RecentDecisionsPanel stats={STATS} recent={recent} onSelectTrace={vi.fn()} />)
    expect(screen.queryByRole('button', { name: /trace/i })).not.toBeInTheDocument()
  })

  it('flags rule-based fallback decisions so they are not read as model reasoning', () => {
    const recent = [
      {
        id: 'f1',
        action: 'buy',
        symbol: 'SOL/USD',
        price: 81.4,
        confidence: 0.55,
        llm_succeeded: false,
        reasoning_summary: 'fallback:skip_reasoning',
        timestamp: '2026-05-31T18:00:00Z',
      },
      {
        id: 'n1',
        action: 'buy',
        symbol: 'BTC/USD',
        price: 73000,
        confidence: 0.8,
        llm_succeeded: true,
        reasoning_summary: 'momentum up',
        timestamp: '2026-05-31T18:01:00Z',
      },
    ]
    render(<RecentDecisionsPanel stats={STATS} recent={recent} />)

    // Header summary counts only the fallback rows against the actionable total.
    expect(screen.getByText('1/2 rule-based')).toBeInTheDocument()
    // Exactly one per-row tag — on the fallback decision, not the real one.
    expect(screen.getAllByText('rule-based')).toHaveLength(1)
    expect(screen.getByText('SOL/USD')).toBeInTheDocument()
    expect(screen.getByText('BTC/USD')).toBeInTheDocument()
  })

  it('shows no fallback markers when every decision used the LLM', () => {
    const recent = [
      {
        id: 'n1',
        action: 'buy',
        symbol: 'BTC/USD',
        price: 73000,
        confidence: 0.8,
        llm_succeeded: true,
        timestamp: '2026-05-31T18:01:00Z',
      },
    ]
    render(<RecentDecisionsPanel stats={STATS} recent={recent} />)
    expect(screen.queryByText(/rule-based/)).not.toBeInTheDocument()
  })
})
