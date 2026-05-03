import { render, screen } from '@testing-library/react'
import { StatusChip } from '@/components/primitives/StatusChip'

describe('StatusChip', () => {
  test('renders status text', () => {
    render(<StatusChip status="ACTIVE" />)
    expect(screen.getByText('ACTIVE')).toBeInTheDocument()
  })

  test('supports buy/sell variants', () => {
    const { rerender } = render(<StatusChip status="BUY" />)
    expect(screen.getByText('BUY')).toBeInTheDocument()
    rerender(<StatusChip status="SELL" />)
    expect(screen.getByText('SELL')).toBeInTheDocument()
  })
})
