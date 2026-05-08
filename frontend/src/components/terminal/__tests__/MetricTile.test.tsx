import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MetricTile } from '../MetricTile'

describe('MetricTile', () => {
  it('renders label and value', () => {
    render(<MetricTile label="Daily P&L" value="+$123.45" />)
    expect(screen.getByText('Daily P&L')).toBeInTheDocument()
    expect(screen.getByText('+$123.45')).toBeInTheDocument()
  })

  it('renders optional hint', () => {
    render(<MetricTile label="L" value="V" hint="Background detail" />)
    expect(screen.getByText('Background detail')).toBeInTheDocument()
  })

  it('omits hint paragraph when not provided', () => {
    const { container } = render(<MetricTile label="L" value="V" />)
    expect(container.querySelectorAll('p')).toHaveLength(2)
  })

  it('applies positive tone class to value', () => {
    const { container } = render(<MetricTile label="L" value="V" tone="pos" />)
    const html = container.innerHTML
    expect(html).toContain('text-emerald-500')
  })

  it('applies negative tone class to value', () => {
    const { container } = render(<MetricTile label="L" value="V" tone="neg" />)
    expect(container.innerHTML).toContain('text-rose-500')
  })

  it('renders icon component when supplied', () => {
    const Icon = (props: { className?: string }) => (
      <svg data-testid="icon" className={props.className} />
    )
    render(<MetricTile label="L" value="V" icon={Icon} />)
    expect(screen.getByTestId('icon')).toBeInTheDocument()
  })
})
