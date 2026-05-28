import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { PipelineStage } from '@/components/dashboard/system/PipelineStage'

describe('PipelineStage', () => {
  it('renders label, count and status label', () => {
    render(<PipelineStage label="Signals" count={42} status="flowing" />)
    expect(screen.getByText('Signals')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('FLOWING')).toBeInTheDocument()
  })

  it('shows STALLED for stalled status with red dot', () => {
    const { container } = render(<PipelineStage label="Market" count={0} status="stalled" />)
    expect(screen.getByText('STALLED')).toBeInTheDocument()
    expect(container.querySelector('.bg-rose-500')).toBeTruthy()
  })

  it('shows IDLE for idle status with amber dot', () => {
    const { container } = render(<PipelineStage label="Orders" count={0} status="idle" />)
    expect(screen.getByText('IDLE')).toBeInTheDocument()
    expect(container.querySelector('.bg-amber-400')).toBeTruthy()
  })

  it('shows LIVE with pulsing emerald dot', () => {
    const { container } = render(<PipelineStage label="Market" count={1000} status="live" />)
    expect(screen.getByText('LIVE')).toBeInTheDocument()
    expect(container.querySelector('.bg-emerald-500.animate-pulse')).toBeTruthy()
  })

  it('hides the chevron when isLast is true', () => {
    const { container } = render(
      <PipelineStage label="Executions" count={5} status="flowing" isLast />,
    )
    expect(container.querySelector('[aria-hidden="true"]')).toBeNull()
  })

  it('shows the chevron when isLast is false', () => {
    const { container } = render(<PipelineStage label="Signals" count={5} status="flowing" />)
    expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull()
  })

  it('formats large counts with locale separators', () => {
    render(<PipelineStage label="Market" count={12345} status="live" />)
    expect(screen.getByText('12,345')).toBeInTheDocument()
  })
})
