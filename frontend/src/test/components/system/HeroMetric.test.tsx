import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Database } from 'lucide-react'

import { HeroMetric } from '@/components/dashboard/system/HeroMetric'

describe('HeroMetric', () => {
  it('renders label, value, and sub', () => {
    render(<HeroMetric label="Throughput" value="2.50/s" sub="100 msgs" status="ok" icon={Database} />)
    expect(screen.getByRole('group', { name: /throughput/i })).toBeInTheDocument()
    expect(screen.getByText('Throughput')).toBeInTheDocument()
    expect(screen.getByText('2.50/s')).toBeInTheDocument()
    expect(screen.getByText('100 msgs')).toBeInTheDocument()
  })

  it('applies the warn tone color', () => {
    render(<HeroMetric label="Latency" value="42s" status="warn" />)
    const value = screen.getByText('42s')
    expect(value.className).toContain('amber-500')
  })

  it('applies the err tone color', () => {
    render(<HeroMetric label="Pipeline" value="Stalled" status="err" />)
    expect(screen.getByText('Stalled').className).toContain('rose-500')
  })

  it('applies the ok tone color', () => {
    render(<HeroMetric label="Pipeline" value="Healthy" status="ok" />)
    expect(screen.getByText('Healthy').className).toContain('emerald-500')
  })

  it('defaults to neutral when no status provided', () => {
    render(<HeroMetric label="Trades" value="42" />)
    expect(screen.getByText('42').className).toContain('slate-700')
  })

  it('omits sub when not provided', () => {
    render(<HeroMetric label="Trades" value="42" />)
    expect(screen.queryByText('100 msgs')).not.toBeInTheDocument()
  })
})
