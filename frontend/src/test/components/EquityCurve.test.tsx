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

import { EquityCurve, buildEquitySeries, getPaddedDomain } from '@/components/dashboard/EquityCurve'

describe('EquityCurve', () => {
  it('renders empty state with no data', () => {
    render(<EquityCurve orders={[]} />)
    expect(screen.getByText(/No equity data yet/i)).toBeInTheDocument()
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
