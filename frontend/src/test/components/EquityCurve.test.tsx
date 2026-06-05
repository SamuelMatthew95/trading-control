import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div data-testid="responsive">{children}</div>,
  AreaChart: ({ children }: { children: ReactNode }) => <div data-testid="area-chart">{children}</div>,
  CartesianGrid: () => <div data-testid="grid" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  Tooltip: () => <div data-testid="tooltip" />,
  ReferenceLine: () => <div data-testid="baseline" />,
  Area: () => <div data-testid="area" />,
}))

import { EquityCurve, buildEquitySeries, getPaddedDomain, getNiceYAxis } from '@/components/dashboard/EquityCurve'

describe('EquityCurve', () => {
  it('renders empty state with no data', () => {
    render(<EquityCurve orders={[]} />)
    expect(screen.getByText(/No equity data yet/i)).toBeInTheDocument()
  })

  it('falls back to the live series when there are no closed orders (open position)', () => {
    render(
      <EquityCurve
        orders={[]}
        liveSeries={[
          { timestamp: 1000, label: '', pnl: -1, delta: -1, equity: -1 },
          { timestamp: 4000, label: '', pnl: -1.06, delta: -0.06, equity: -1.06 },
        ]}
      />,
    )
    expect(screen.queryByText(/No equity data yet/i)).not.toBeInTheDocument()
    expect(screen.getByTestId('area-chart')).toBeInTheDocument()
    expect(screen.getByText(/Live · marks to market/i)).toBeInTheDocument()
  })

  it('prefers the realized order curve over the live series when trades have closed', () => {
    render(
      <EquityCurve
        orders={[{ created_at: '2026-01-01T00:00:00Z', pnl: 10 }]}
        liveSeries={[{ timestamp: 1000, label: '', pnl: -1, delta: -1, equity: -1 }]}
      />,
    )
    // The realized curve wins, so the live badge must not show.
    expect(screen.queryByText(/Live · marks to market/i)).not.toBeInTheDocument()
    expect(screen.getByText('Cumulative P&L')).toBeInTheDocument()
  })

  it('renders chart scaffolding for valid data', () => {
    render(
      <EquityCurve
        orders={[
          { created_at: '2026-01-01T00:00:00Z', pnl: 10 },
          { created_at: '2026-01-01T00:01:00Z', pnl: -5 },
        ]}
      />,
    )

    expect(screen.getByTestId('area-chart')).toBeInTheDocument()
    expect(screen.getByTestId('x-axis')).toBeInTheDocument()
    expect(screen.getByTestId('y-axis')).toBeInTheDocument()
    expect(screen.getByTestId('tooltip')).toBeInTheDocument()
    expect(screen.getByTestId('baseline')).toBeInTheDocument()
  })

  it('sorts by timestamp and deduplicates timestamps while ignoring invalid points', () => {
    const series = buildEquitySeries([
      { created_at: '2026-01-01T00:02:00Z', pnl: 5 },
      { created_at: '2026-01-01T00:01:00Z', pnl: 3 },
      { created_at: '2026-01-01T00:01:00Z', pnl: 2 },
      { created_at: 'bad-date', pnl: 100 },
      { created_at: '2026-01-01T00:03:00Z', pnl: Number.NaN },
    ])

    expect(series).toHaveLength(2)
    expect(series[0].timestamp).toBeLessThan(series[1].timestamp)
    expect(series[0].equity).toBe(5)
    expect(series[1].equity).toBe(10)
  })

  it('accepts string-encoded pnl values', () => {
    const series = buildEquitySeries([
      { created_at: '2026-01-01T00:00:00Z', pnl: '10.5' },
      { created_at: '2026-01-01T00:01:00Z', pnl: '-2.5' },
    ])

    expect(series).toHaveLength(2)
    expect(series[0].equity).toBe(10.5)
    expect(series[1].equity).toBe(8)
    expect(series[0].delta).toBe(10.5)
    expect(series[1].delta).toBe(-2.5)
  })

  it('uses zero-baseline endpoint to determine gain/loss color', () => {
    render(
      <EquityCurve
        orders={[
          { created_at: '2026-01-01T00:00:00Z', pnl: 100 },
          { created_at: '2026-01-01T00:01:00Z', pnl: -50 },
        ]}
      />,
    )

    expect(screen.getByText('Cumulative P&L').nextElementSibling).toHaveClass('text-emerald-500')
  })

  it('shows net metric from zero baseline instead of first plotted point', () => {
    render(
      <EquityCurve
        orders={[
          { created_at: '2026-01-01T00:00:00Z', pnl: 100 },
          { created_at: '2026-01-01T00:01:00Z', pnl: -50 },
        ]}
      />,
    )

    const netLabel = screen.getByText('Net')
    expect(netLabel.nextElementSibling).toHaveTextContent('+$50.00')
    expect(netLabel.nextElementSibling).toHaveClass('text-emerald-500')
  })

  it('produces clean, nicely-stepped y-axis ticks for small P&L (no -$6.15 junk)', () => {
    // A position worth a couple of dollars sitting at -$1.15 used to get a
    // domain like [-6.15, 5] with junk labels (-0.15, -3.15, -6.15). Ticks must
    // now sit on a 0-anchored grid of a single nice step.
    const series = [
      { timestamp: 1000, label: '', pnl: -1.15, delta: -1.15, equity: -1.15 },
      { timestamp: 4000, label: '', pnl: -1.15, delta: 0, equity: -1.15 },
    ]
    const { domain, ticks } = getNiceYAxis(series)
    const gaps = ticks.slice(1).map((t, i) => Number((t - ticks[i]).toFixed(6)))
    expect(new Set(gaps).size).toBe(1) // evenly spaced
    const step = gaps[0]
    expect(step).toBeGreaterThan(0)
    // Each tick is an integer multiple of the step (the -0.15/-3.15 junk was not).
    for (const t of ticks) expect(Number.isInteger(Number((t / step).toFixed(6)))).toBe(true)
    expect(ticks).toContain(0)
    expect(domain[0]).toBeLessThan(-1.15)
    expect(domain[1]).toBeGreaterThanOrEqual(0)
  })

  it('floors the step at $0.01 for sub-cent P&L (no all-zero or -$0.00 ticks)', () => {
    // Extreme edge: equity ~3e-7 used to round every tick to 0 (toFixed(6)) and
    // could emit a negative-zero tick rendering as "-$0.00".
    const series = [
      { timestamp: 1000, label: '', pnl: 3e-7, delta: 0, equity: 3e-7 },
      { timestamp: 4000, label: '', pnl: 3e-7, delta: 0, equity: 3e-7 },
    ]
    const { ticks } = getNiceYAxis(series)
    expect(ticks.length).toBeGreaterThan(1)
    expect(new Set(ticks).size).toBe(ticks.length) // distinct, not all 0
    for (const t of ticks) {
      expect(Object.is(t, -0)).toBe(false) // no negative zero → no "-$0.00"
      expect(Math.round(t * 100) / 100).toBe(t) // on the cent grid
    }
    expect(ticks).toContain(0)
  })

  it('returns padded y-axis domain', () => {
    const series = buildEquitySeries([
      { created_at: '2026-01-01T00:00:00Z', pnl: 100 },
      { created_at: '2026-01-01T00:01:00Z', pnl: 100 },
    ])
    const [min, max] = getPaddedDomain(series)

    expect(min).toBeLessThanOrEqual(0)
    expect(max).toBeGreaterThan(200)
  })
})
