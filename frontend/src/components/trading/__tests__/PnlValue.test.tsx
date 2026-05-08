import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PnlValue } from '../PnlValue'
import { TradeSideChip } from '../TradeSideChip'
import { GradeChip } from '../GradeChip'

describe('PnlValue', () => {
  it('renders missing placeholder for null', () => {
    render(<PnlValue value={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('renders +$X for positive numbers', () => {
    render(<PnlValue value={123.45} />)
    expect(screen.getByText('+$123.45')).toBeInTheDocument()
  })

  it('renders -$X for negative numbers', () => {
    render(<PnlValue value={-42} />)
    expect(screen.getByText('-$42.00')).toBeInTheDocument()
  })

  it('renders $0.00 with no sign for exact zero', () => {
    render(<PnlValue value={0} />)
    expect(screen.getByText('$0.00')).toBeInTheDocument()
  })

  it('appends signed percent suffix when supplied', () => {
    render(<PnlValue value={50} percent={2.5} />)
    expect(screen.getByText('+$50.00 (+2.5%)')).toBeInTheDocument()
  })

  it('does not append percent when percent is null', () => {
    render(<PnlValue value={50} />)
    expect(screen.getByText('+$50.00')).toBeInTheDocument()
  })

  it('uses pos tone class on positive values', () => {
    const { container } = render(<PnlValue value={1} />)
    expect(container.innerHTML).toContain('text-emerald-500')
  })

  it('uses neg tone class on negative values', () => {
    const { container } = render(<PnlValue value={-1} />)
    expect(container.innerHTML).toContain('text-rose-500')
  })
})

describe('TradeSideChip', () => {
  it('renders BUY uppercase with positive tone', () => {
    const { container } = render(<TradeSideChip side="buy" />)
    expect(screen.getByText('BUY')).toBeInTheDocument()
    expect(container.innerHTML).toContain('emerald')
  })

  it('renders SELL uppercase with negative tone', () => {
    const { container } = render(<TradeSideChip side="sell" />)
    expect(screen.getByText('SELL')).toBeInTheDocument()
    expect(container.innerHTML).toContain('rose')
  })

  it('renders LONG with positive tone', () => {
    const { container } = render(<TradeSideChip side="long" />)
    expect(screen.getByText('LONG')).toBeInTheDocument()
    expect(container.innerHTML).toContain('emerald')
  })

  it('renders N/A for missing side', () => {
    render(<TradeSideChip side={null} />)
    expect(screen.getByText('N/A')).toBeInTheDocument()
  })
})

describe('GradeChip', () => {
  it('renders nothing when grade is null', () => {
    const { container } = render(<GradeChip grade={null} />)
    expect(container.innerHTML).toBe('')
  })

  it('renders A with positive tone', () => {
    const { container } = render(<GradeChip grade="A" />)
    expect(screen.getByText('A')).toBeInTheDocument()
    expect(container.innerHTML).toContain('emerald')
  })

  it('renders C with warning tone', () => {
    const { container } = render(<GradeChip grade="C" />)
    expect(screen.getByText('C')).toBeInTheDocument()
    expect(container.innerHTML).toContain('amber')
  })

  it('renders F with negative tone', () => {
    const { container } = render(<GradeChip grade="F" />)
    expect(screen.getByText('F')).toBeInTheDocument()
    expect(container.innerHTML).toContain('rose')
  })
})
