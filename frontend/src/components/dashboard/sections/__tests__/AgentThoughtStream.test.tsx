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

  it('drops logs that have no agent name (the "N/A" rows)', () => {
    const logs = [
      {
        id: 'a',
        agent_name: 'reasoning_agent',
        message: 'Rule-based fallback decision',
        timestamp: '2026-05-08T10:00:00Z',
      },
      {
        id: 'b',
        agent_name: '',
        message: 'HOLD (30%)',
        timestamp: '2026-05-08T10:00:01Z',
      },
    ] as unknown as AgentLog[]

    render(<AgentThoughtStream logs={logs} onTraceClick={onTraceClick} />)

    expect(screen.getByText('reasoning_agent')).toBeInTheDocument()
    expect(screen.queryByText('N/A')).not.toBeInTheDocument()
    expect(screen.queryByText(/HOLD \(30%\)$/)).not.toBeInTheDocument()
  })

  it('translates `fallback:<mode>` tokens embedded inside a longer message', () => {
    const logs = [
      {
        id: '1',
        agent_name: 'reasoning_agent',
        message: 'HOLD (30%) — fallback:skip_reasoning',
        timestamp: '2026-05-08T10:00:00Z',
      },
    ] as unknown as AgentLog[]

    render(<AgentThoughtStream logs={logs} onTraceClick={onTraceClick} />)

    expect(
      screen.getByText('HOLD (30%) — Rule-based fallback decision'),
    ).toBeInTheDocument()
    // The raw token must NOT leak through.
    expect(screen.queryByText(/fallback:skip_reasoning/)).not.toBeInTheDocument()
  })

  it('also handles the bare-prefix fallback form', () => {
    const logs = [
      {
        id: '1',
        agent_name: 'reasoning_agent',
        message: 'fallback:reject_signal',
        timestamp: '2026-05-08T10:00:00Z',
      },
    ] as unknown as AgentLog[]

    render(<AgentThoughtStream logs={logs} onTraceClick={onTraceClick} />)
    expect(
      screen.getByText('Rule-based fallback: signal rejected'),
    ).toBeInTheDocument()
  })

  it('falls back to "LLM unavailable" for unknown fallback modes', () => {
    const logs = [
      {
        id: '1',
        agent_name: 'reasoning_agent',
        message: 'fallback:totally_new_mode',
        timestamp: '2026-05-08T10:00:00Z',
      },
    ] as unknown as AgentLog[]

    render(<AgentThoughtStream logs={logs} onTraceClick={onTraceClick} />)
    expect(screen.getByText('LLM unavailable')).toBeInTheDocument()
  })

  it('dedupes per (trace_id, message) so paired decision/summary writes do not both render', () => {
    const logs = [
      {
        id: '1',
        agent_name: 'reasoning_agent',
        message: 'Rule-based fallback decision',
        trace_id: 'trace-abc',
        timestamp: '2026-05-08T10:00:00Z',
      },
      {
        id: '2',
        agent_name: 'reasoning_agent',
        message: 'Rule-based fallback decision',
        trace_id: 'trace-abc',
        timestamp: '2026-05-08T10:00:01Z',
      },
    ] as unknown as AgentLog[]

    render(<AgentThoughtStream logs={logs} onTraceClick={onTraceClick} />)
    expect(screen.getAllByText('Rule-based fallback decision')).toHaveLength(1)
  })
})
