import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AgentThoughtStream } from '../AgentThoughtStream'
import type { AgentLog } from '@/stores/useCodexStore'

const onTraceClick = vi.fn()

describe('AgentThoughtStream', () => {
  it('renders empty state when there are no logs', () => {
    render(<AgentThoughtStream logs={[]} onTraceClick={onTraceClick} />)
    expect(screen.getByText('No active agents')).toBeInTheDocument()
  })

  it('drops logs that have no agent name', () => {
    const logs = [
      {
        id: 'a',
        agent_name: 'reasoning_agent',
        message: 'Buy BTC/USD on momentum + RSI confluence',
        timestamp: '2026-05-08T10:00:00Z',
      },
      {
        id: 'b',
        agent_name: '',
        message: 'orphan log',
        timestamp: '2026-05-08T10:00:01Z',
      },
    ] as unknown as AgentLog[]

    render(<AgentThoughtStream logs={logs} onTraceClick={onTraceClick} />)

    expect(screen.getByText('reasoning_agent')).toBeInTheDocument()
    expect(screen.queryByText('orphan log')).not.toBeInTheDocument()
    expect(screen.queryByText('N/A')).not.toBeInTheDocument()
  })

  it('translates `fallback:<mode>` markers (and surfaces them as a banner, not a row)', () => {
    const logs = [
      {
        id: '1',
        agent_name: 'reasoning_agent',
        message: 'fallback:skip_reasoning',
        timestamp: '2026-05-08T10:00:00Z',
      },
    ] as unknown as AgentLog[]

    render(<AgentThoughtStream logs={logs} onTraceClick={onTraceClick} />)
    // Fallback messages are surfaced via a single banner, not as a thought row.
    expect(
      screen.getByText('1 rule-based decision (LLM unavailable)'),
    ).toBeInTheDocument()
  })

  it('collapses N identical fallback decisions into ONE banner with the count', () => {
    const logs = Array.from({ length: 5 }).map((_, i) => ({
      id: String(i),
      agent_name: 'reasoning_agent',
      message: 'fallback:skip_reasoning',
      trace_id: `trace-${i}`,
      timestamp: `2026-05-08T10:00:${String(i).padStart(2, '0')}Z`,
    })) as unknown as AgentLog[]

    render(<AgentThoughtStream logs={logs} onTraceClick={onTraceClick} />)

    expect(
      screen.getByText('5 rule-based decisions (LLM unavailable)'),
    ).toBeInTheDocument()
    // The phrase must NOT appear five times as separate rows.
    expect(screen.queryAllByText(/Rule-based fallback decision/)).toHaveLength(0)
  })

  it('dedupes identical NON-fallback messages and shows a ×N badge', () => {
    const logs = [
      {
        id: '1',
        agent_name: 'reasoning_agent',
        message: 'Holding BTC/USD: signal weak',
        trace_id: 'trace-a',
        timestamp: '2026-05-08T10:00:00Z',
      },
      {
        id: '2',
        agent_name: 'reasoning_agent',
        message: 'Holding BTC/USD: signal weak',
        trace_id: 'trace-b',
        timestamp: '2026-05-08T10:00:01Z',
      },
      {
        id: '3',
        agent_name: 'reasoning_agent',
        message: 'Holding BTC/USD: signal weak',
        trace_id: 'trace-c',
        timestamp: '2026-05-08T10:00:02Z',
      },
    ] as unknown as AgentLog[]

    render(<AgentThoughtStream logs={logs} onTraceClick={onTraceClick} />)

    expect(screen.getAllByText('Holding BTC/USD: signal weak')).toHaveLength(1)
    expect(screen.getByText('×3')).toBeInTheDocument()
  })

  it('shows distinct thoughts on separate rows', () => {
    const logs = [
      {
        id: '1',
        agent_name: 'reasoning_agent',
        message: 'Buy BTC/USD on momentum',
        timestamp: '2026-05-08T10:00:00Z',
      },
      {
        id: '2',
        agent_name: 'reasoning_agent',
        message: 'Sell ETH/USD on RSI overbought',
        timestamp: '2026-05-08T10:00:01Z',
      },
    ] as unknown as AgentLog[]

    render(<AgentThoughtStream logs={logs} onTraceClick={onTraceClick} />)

    expect(screen.getByText('Buy BTC/USD on momentum')).toBeInTheDocument()
    expect(screen.getByText('Sell ETH/USD on RSI overbought')).toBeInTheDocument()
  })

  it('translates an embedded fallback marker (HOLD (30%) — fallback:skip_reasoning)', () => {
    const logs = [
      {
        id: '1',
        agent_name: 'reasoning_agent',
        message: 'HOLD (30%) — fallback:skip_reasoning',
        timestamp: '2026-05-08T10:00:00Z',
      },
    ] as unknown as AgentLog[]

    render(<AgentThoughtStream logs={logs} onTraceClick={onTraceClick} />)
    // Embedded form translates inline (it's not the canonical fallback row,
    // so it stays in the thought list rather than the banner).
    expect(
      screen.getByText('HOLD (30%) — Rule-based fallback decision'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/fallback:skip_reasoning/)).not.toBeInTheDocument()
  })
})
