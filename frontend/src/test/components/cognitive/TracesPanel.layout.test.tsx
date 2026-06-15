import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { TracesPanel } from '@/components/dashboard/cognitive/TracesPanel'
import type { TradeTrace } from '@/types/cognitive'

// A trace whose perception chain carries a long microstructure output — the
// exact shape that overflowed the mobile viewport and shifted the whole page.
const trace = {
  trace_id: 'baf8393f-cf6c-46e3-97ad-7d4199767ede',
  decision: {
    action: 'hold',
    confidence: 0.3,
    symbol: 'BTC/USD',
    price: 63741.09,
    reasoning_summary: 'composite_score low at 0.3',
    tools_used: [
      { name: 'get_order_book_depth', latency_ms: 421, success: true, outputs: { spread_bps: 9, imbalance: 0.004, count: 10 } },
      { name: 'get_news_sentiment', latency_ms: 378, success: true, outputs: { count: 10 } },
    ],
  },
  outcome: null,
  grade: null,
} as unknown as TradeTrace

describe('TracesPanel layout (mobile overflow guards)', () => {
  it('truncates the trace_id instead of forcing horizontal overflow', () => {
    render(<TracesPanel traces={[trace]} />)
    const id = screen.getByText('baf8393f-cf6c-46e3-97ad-7d4199767ede')
    expect(id.className).toContain('truncate')
  })

  it('wraps long tool-output rows so they stay inside the card', () => {
    render(<TracesPanel traces={[trace]} />)
    // The first trace is expanded by default; the order-book tool row is shown.
    const toolName = screen.getByText('get_order_book_depth')
    const row = toolName.parentElement
    expect(row?.className).toContain('flex-wrap')
  })
})
