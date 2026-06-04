import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { LiveNumber } from '@/components/dashboard/LiveNumber'

describe('LiveNumber', () => {
  it('renders its formatted children', () => {
    render(<LiveNumber value={10}>$10.00</LiveNumber>)
    expect(screen.getByText('$10.00')).toBeInTheDocument()
  })

  it('flashes up when the value increases', async () => {
    const { rerender, container } = render(<LiveNumber value={10}>$10.00</LiveNumber>)
    rerender(<LiveNumber value={20}>$20.00</LiveNumber>)
    await waitFor(() => expect(container.querySelector('[data-flash="up"]')).not.toBeNull())
  })

  it('flashes down when the value decreases', async () => {
    const { rerender, container } = render(<LiveNumber value={20}>$20.00</LiveNumber>)
    rerender(<LiveNumber value={5}>$5.00</LiveNumber>)
    await waitFor(() => expect(container.querySelector('[data-flash="down"]')).not.toBeNull())
  })

  it('does not flash on mount or when the value is unchanged', () => {
    const { rerender, container } = render(<LiveNumber value={10}>$10.00</LiveNumber>)
    expect(container.querySelector('[data-flash]')).toBeNull()
    rerender(<LiveNumber value={10}>$10.00</LiveNumber>)
    expect(container.querySelector('[data-flash]')).toBeNull()
  })
})
