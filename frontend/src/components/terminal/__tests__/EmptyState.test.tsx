import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { EmptyState } from '../EmptyState'
import { LoadingState } from '../LoadingState'
import { ErrorState } from '../ErrorState'

describe('EmptyState', () => {
  it('renders the supplied message', () => {
    render(<EmptyState message="No orders today" />)
    expect(screen.getByText('No orders today')).toBeInTheDocument()
  })

  it('uses dashed border styling (so it visually differs from real cards)', () => {
    const { container } = render(<EmptyState message="x" />)
    const root = container.firstElementChild as HTMLElement
    expect(root.className).toContain('border-dashed')
  })

  it('renders an icon when supplied', () => {
    const Icon = (props: { className?: string }) => (
      <svg data-testid="empty-icon" className={props.className} />
    )
    render(<EmptyState message="x" icon={Icon} />)
    expect(screen.getByTestId('empty-icon')).toBeInTheDocument()
  })
})

describe('LoadingState', () => {
  it('renders default text "Loading…" when no message provided', () => {
    render(<LoadingState />)
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('renders provided message', () => {
    render(<LoadingState message="Fetching trades" />)
    expect(screen.getByText('Fetching trades')).toBeInTheDocument()
  })
})

describe('ErrorState', () => {
  it('renders message', () => {
    render(<ErrorState message="Failed to load trace" />)
    expect(screen.getByText('Failed to load trace')).toBeInTheDocument()
  })

  it('renders detail when provided', () => {
    render(<ErrorState message="x" detail="HTTP 503" />)
    expect(screen.getByText('HTTP 503')).toBeInTheDocument()
  })

  it('uses negative tone styling', () => {
    const { container } = render(<ErrorState message="x" />)
    expect(container.innerHTML).toContain('rose')
  })
})
