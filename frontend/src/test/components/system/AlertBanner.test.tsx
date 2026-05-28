import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AlertTriangle } from 'lucide-react'

import { AlertBanner } from '@/components/dashboard/system/AlertBanner'

describe('AlertBanner', () => {
  it('renders the message and detail', () => {
    render(
      <AlertBanner
        variant="warn"
        icon={AlertTriangle}
        message="Signals stalled"
        detail="No new market events for 30s"
      />,
    )
    expect(screen.getByText('Signals stalled')).toBeInTheDocument()
    expect(screen.getByText('No new market events for 30s')).toBeInTheDocument()
  })

  it('declares the alert role', () => {
    render(<AlertBanner variant="err" icon={AlertTriangle} message="DB down" />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('uses warn palette for warn variant', () => {
    render(<AlertBanner variant="warn" icon={AlertTriangle} message="x" />)
    expect(screen.getByRole('alert').className).toContain('amber')
  })

  it('uses err palette for err variant', () => {
    render(<AlertBanner variant="err" icon={AlertTriangle} message="x" />)
    expect(screen.getByRole('alert').className).toContain('rose')
  })

  it('uses info palette for info variant', () => {
    render(<AlertBanner variant="info" icon={AlertTriangle} message="x" />)
    expect(screen.getByRole('alert').className).toContain('blue')
  })

  it('uses ok palette for ok variant', () => {
    render(<AlertBanner variant="ok" icon={AlertTriangle} message="x" />)
    expect(screen.getByRole('alert').className).toContain('emerald')
  })

  it('omits detail when not provided', () => {
    render(<AlertBanner variant="warn" icon={AlertTriangle} message="Just a heading" />)
    expect(screen.getByText('Just a heading')).toBeInTheDocument()
    expect(screen.queryByText('No new market events for 30s')).not.toBeInTheDocument()
  })
})
