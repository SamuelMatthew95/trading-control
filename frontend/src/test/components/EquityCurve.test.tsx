import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
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

import {
  EquityCurve,
  buildEquitySeries,
  buildCombinedSeries,
  buildRenderSeries,
  computeWindowStats,
  filterByRange,
  getPaddedDomain,
  getNiceYAxis,
  EQUITY_RANGES,
} from '@/components/dashboard/EquityCurve'

const livePoint = (timestamp: number, equity: number) => ({
  timestamp,
  label: '',
  pnl: equity,
  delta: 0,
  equity,
})

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

describe('buildCombinedSeries', () => {
  it('uses the live series wholesale at cold start (no closed orders)', () => {
    const combined = buildCombinedSeries([], [livePoint(1000, -1), livePoint(2000, -1.1)])
    expect(combined).toHaveLength(2)
    expect(combined.every((p) => p.live)).toBe(true)
  })

  it('appends only the live tail newer than the last realized point', () => {
    const lastTs = Date.parse('2026-01-01T00:00:00Z')
    const combined = buildCombinedSeries(
      [{ created_at: '2026-01-01T00:00:00Z', pnl: 10 }],
      [livePoint(lastTs - 1000, 99), livePoint(lastTs + 1000, 12)],
    )
    expect(combined).toHaveLength(2)
    expect(combined[0]).toMatchObject({ live: false, equity: 10 })
    // Stale live sample (before the close) dropped; the newer one continues the curve.
    expect(combined[1]).toMatchObject({ live: true, equity: 12 })
  })
})

describe('filterByRange', () => {
  const HOUR = 60 * 60 * 1000
  const MIN = 60 * 1000
  const now = 100_000_000
  const series = [
    { ...livePoint(now - 2 * HOUR, -1), live: true },
    { ...livePoint(now - 30 * MIN, -0.5), live: true },
    { ...livePoint(now - 1000, -0.2), live: true },
  ]

  it('keeps everything for ALL', () => {
    expect(filterByRange(series, 'ALL', now)).toHaveLength(3)
  })

  it('slices to the 1H window', () => {
    expect(filterByRange(series, '1H', now)).toHaveLength(2)
  })

  it('slices to the LIVE (15m) window', () => {
    expect(filterByRange(series, 'LIVE', now)).toHaveLength(1)
  })
})

describe('computeWindowStats', () => {
  const full = [
    { ...livePoint(1000, 5), live: false },
    { ...livePoint(2000, 8), live: false },
    { ...livePoint(3000, 6), live: false },
  ]

  it('measures change from the baseline just before the window', () => {
    const stats = computeWindowStats(full, full.slice(1))
    expect(stats).toMatchObject({ baseline: 5, last: 6, change: 1, peak: 8, trough: 6, range: 2 })
  })

  it('uses a zero baseline when the window reaches inception (ALL)', () => {
    const stats = computeWindowStats(full, full)
    expect(stats).toMatchObject({ baseline: 0, last: 6, change: 6, peak: 8, trough: 5, range: 3 })
  })

  it('returns null for an empty window', () => {
    expect(computeWindowStats(full, [])).toBeNull()
  })
})

describe('buildRenderSeries', () => {
  it('breaks the line across a large gap between live samples', () => {
    const render = buildRenderSeries([
      { ...livePoint(0, 0), live: true },
      { ...livePoint(3000, 1), live: true }, // 3s — continuous
      { ...livePoint(3000 + 60_000, 2), live: true }, // 60s gap — break
    ])
    expect(render).toHaveLength(4)
    expect(render.filter((p) => p.equity === null)).toHaveLength(1)
  })

  it('never breaks the realized backbone, even across long spans', () => {
    const render = buildRenderSeries([
      { ...livePoint(0, 0), live: false },
      { ...livePoint(10_000_000, 5), live: false },
    ])
    expect(render).toHaveLength(2)
    expect(render.some((p) => p.equity === null)).toBe(false)
  })
})

describe('EquityCurve range selector', () => {
  it('renders all range tabs with ALL active by default', () => {
    render(<EquityCurve orders={[{ created_at: '2026-01-01T00:00:00Z', pnl: 10 }]} />)
    for (const key of EQUITY_RANGES) {
      expect(screen.getByRole('button', { name: key })).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: 'ALL' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('disables ranges longer than the available history at cold start', () => {
    const now = Date.now()
    render(<EquityCurve orders={[]} liveSeries={[livePoint(now - 6000, -1), livePoint(now - 3000, -1.05)]} />)
    expect(screen.getByRole('button', { name: '1H' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '1M' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'LIVE' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'ALL' })).toBeEnabled()
  })

  it('switches the active range when a tab is clicked', () => {
    const now = Date.now()
    render(<EquityCurve orders={[]} liveSeries={[livePoint(now - 6000, -1), livePoint(now - 3000, -1.05)]} />)
    const liveTab = screen.getByRole('button', { name: 'LIVE' })
    fireEvent.click(liveTab)
    expect(liveTab).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'ALL' })).toHaveAttribute('aria-pressed', 'false')
  })
})
