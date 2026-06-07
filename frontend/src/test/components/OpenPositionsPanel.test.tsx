import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { OpenPositionsPanel } from '@/components/dashboard/OpenPositionsPanel'
import { useCodexStore } from '@/stores/useCodexStore'

const POSITION = {
  symbol: 'BTC/USD',
  side: 'long',
  quantity: 0.5,
  entry_price: 40000,
  current_price: 42000,
  pnl: 1000,
  pnl_percent: 5,
}

describe('OpenPositionsPanel drill-down', () => {
  beforeEach(() => {
    useCodexStore.setState({ positions: [], prices: {}, tradeFeed: [] })
  })

  it('shows the empty state with no positions', () => {
    render(<OpenPositionsPanel />)
    expect(screen.getByText('No open positions')).toBeInTheDocument()
  })

  it('opens the position detail modal when a row is clicked', () => {
    useCodexStore.setState({
      positions: [POSITION],
      prices: {},
      tradeFeed: [
        {
          id: 't1',
          symbol: 'BTC/USD',
          side: 'buy',
          qty: 0.5,
          entry_price: 40000,
          exit_price: 42000,
          pnl: 1000,
          pnl_percent: 5,
          order_id: 'o1',
          execution_trace_id: null,
          signal_trace_id: null,
          grade: 'A',
          grade_score: 90,
          status: 'closed',
          filled_at: null,
          graded_at: null,
          reflected_at: null,
          created_at: null,
        },
      ],
    })
    render(<OpenPositionsPanel />)

    // Modal closed initially.
    expect(screen.queryByText('Recent trades · BTC/USD')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /View BTC\/USD position details/i }))

    // Modal opened: header + the symbol's trade history section.
    expect(screen.getByText('Position · BTC/USD')).toBeInTheDocument()
    expect(screen.getByText('Recent trades · BTC/USD')).toBeInTheDocument()
  })
})
