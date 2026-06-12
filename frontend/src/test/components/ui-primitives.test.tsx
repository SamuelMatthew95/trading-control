/**
 * Shared UI primitive contracts — the pieces every dashboard surface composes.
 * Focus: behavioural guarantees (clamping, ARIA, tone routing, escape-to-close),
 * not pixel styling.
 */
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { LoadingState, Skeleton } from '@/components/ui/loading'
import { Meter } from '@/components/ui/meter'
import { Modal } from '@/components/ui/modal'
import { MetricTile, StatTile } from '@/components/ui/stat-tile'

describe('Button', () => {
  it('defaults to type="button" so it never submits forms accidentally', () => {
    render(<Button>Go</Button>)
    expect(screen.getByRole('button', { name: 'Go' })).toHaveAttribute('type', 'button')
  })

  it('routes tonal colour through the Tone system', () => {
    render(
      <Button variant="tonal" tone="danger">
        Reject
      </Button>,
    )
    expect(screen.getByRole('button', { name: 'Reject' }).className).toContain('text-danger')
  })

  it('disables interaction when disabled', () => {
    const onClick = vi.fn()
    render(
      <Button disabled onClick={onClick}>
        Nope
      </Button>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Nope' }))
    expect(onClick).not.toHaveBeenCalled()
  })
})

describe('Badge', () => {
  it('routes soft and outlined variants through the Tone maps', () => {
    const { rerender } = render(<Badge tone="success">ok</Badge>)
    expect(screen.getByText('ok').className).toContain('text-success')
    rerender(
      <Badge tone="warning" variant="outlined">
        ok
      </Badge>,
    )
    expect(screen.getByText('ok').className).toContain('border-warning/30')
  })
})

describe('Meter', () => {
  it('exposes progressbar semantics and clamps out-of-range values', () => {
    const { rerender } = render(<Meter value={250} label="progress" />)
    const bar = screen.getByRole('progressbar', { name: 'progress' })
    expect(bar).toHaveAttribute('aria-valuenow', '100')
    rerender(<Meter value={-5} label="progress" />)
    expect(screen.getByRole('progressbar', { name: 'progress' })).toHaveAttribute(
      'aria-valuenow',
      '0',
    )
  })
})

describe('Modal', () => {
  it('renders dialog semantics and closes on Escape and backdrop click', () => {
    const onClose = vi.fn()
    render(
      <Modal onClose={onClose} title="Detail">
        <p>body</p>
      </Modal>,
    )
    expect(screen.getByRole('dialog', { name: 'Detail' })).toBeInTheDocument()

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('presentation'))
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('does not close when clicking inside the panel', () => {
    const onClose = vi.fn()
    render(
      <Modal onClose={onClose} title="Detail">
        <p>body</p>
      </Modal>,
    )
    fireEvent.click(screen.getByText('body'))
    expect(onClose).not.toHaveBeenCalled()
  })
})

describe('StatTile / MetricTile', () => {
  it('renders label, value, and context lines', () => {
    render(<StatTile label="Win Rate" value="61%" lines={['12 of 20 closed']} />)
    expect(screen.getByText('Win Rate')).toBeInTheDocument()
    expect(screen.getByText('61%')).toBeInTheDocument()
    expect(screen.getByText('12 of 20 closed')).toBeInTheDocument()
  })

  it('MetricTile renders value over label', () => {
    render(<MetricTile label="events" value="1,234" />)
    expect(screen.getByText('events')).toBeInTheDocument()
    expect(screen.getByText('1,234')).toBeInTheDocument()
  })
})

describe('EmptyState / LoadingState', () => {
  it('renders message and optional hint', () => {
    render(<EmptyState message="Nothing yet" hint="It will appear soon" />)
    expect(screen.getByText('Nothing yet')).toBeInTheDocument()
    expect(screen.getByText('It will appear soon')).toBeInTheDocument()
  })

  it('LoadingState is a polite live region; Skeleton is aria-hidden', () => {
    const { container } = render(
      <>
        <LoadingState />
        <Skeleton className="h-3" />
      </>,
    )
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite')
    expect(container.querySelector('[aria-hidden]')).not.toBeNull()
  })
})
