import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import { TraceModal } from '@/components/dashboard/TraceModal'

function fetchResponding(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

describe('TraceModal', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => vi.unstubAllGlobals())

  it('shows a calm notice (not an error) when the backend has no trace (404)', async () => {
    // Regression: system notifications carry a trace_id but never write
    // pipeline rows — the backend 404s with {"detail":"Trace not found"} and
    // the modal rendered a danger-toned "Failed to load trace".
    vi.stubGlobal('fetch', fetchResponding(404, { detail: 'Trace not found' }))
    render(<TraceModal traceId="0300480c-ae7f-45aa-9000-000000000000" onClose={() => {}} />)

    await waitFor(() =>
      expect(screen.getByText(/No pipeline trace was recorded/)).toBeInTheDocument(),
    )
    expect(screen.queryByText(/Could not load this trace/)).not.toBeInTheDocument()
    expect(screen.getByText(/No pipeline trace was recorded/).className).not.toContain('danger')
  })

  it('shows the danger-toned error only for real API failures (500)', async () => {
    vi.stubGlobal('fetch', fetchResponding(500, { detail: 'boom' }))
    render(<TraceModal traceId="11111111-1111-4111-8111-111111111111" onClose={() => {}} />)

    await waitFor(() =>
      expect(screen.getByText(/Could not load this trace/)).toBeInTheDocument(),
    )
    expect(screen.queryByText(/No pipeline trace was recorded/)).not.toBeInTheDocument()
  })

  it('renders agent runs when the trace exists', async () => {
    vi.stubGlobal(
      'fetch',
      fetchResponding(200, {
        trace_id: '22222222-2222-4222-8222-222222222222',
        agent_runs: [
          { agent_name: 'SIGNAL_AGENT', run_type: 'analysis', status: 'completed', execution_time_ms: 12 },
        ],
        agent_logs: [],
        agent_grades: [],
      }),
    )
    render(<TraceModal traceId="22222222-2222-4222-8222-222222222222" onClose={() => {}} />)

    await waitFor(() => expect(screen.getByText('SIGNAL_AGENT')).toBeInTheDocument())
    expect(screen.getByText('Agent Runs')).toBeInTheDocument()
    expect(screen.queryByText(/No pipeline trace was recorded/)).not.toBeInTheDocument()
  })

  it('shows the empty-trace notice when the trace exists but has no rows', async () => {
    vi.stubGlobal(
      'fetch',
      fetchResponding(200, {
        trace_id: '33333333-3333-4333-8333-333333333333',
        agent_runs: [],
        agent_logs: [],
        agent_grades: [],
      }),
    )
    render(<TraceModal traceId="33333333-3333-4333-8333-333333333333" onClose={() => {}} />)

    await waitFor(() =>
      expect(screen.getByText(/No pipeline trace was recorded/)).toBeInTheDocument(),
    )
  })
})
