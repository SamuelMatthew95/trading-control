import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusChip } from '../StatusChip'
import { TONE_CLASSES } from '@/lib/state'

describe('StatusChip', () => {
  it('renders label uppercased to caller text', () => {
    render(<StatusChip label="LIVE" tone="pos" />)
    expect(screen.getByText('LIVE')).toBeInTheDocument()
  })

  it('uses positive tone classes', () => {
    const { container } = render(<StatusChip label="OK" tone="pos" />)
    const span = container.querySelector('span')
    expect(span?.className).toContain('text-emerald-600')
  })

  it('uses negative tone classes', () => {
    const { container } = render(<StatusChip label="FAIL" tone="neg" />)
    const span = container.querySelector('span')
    expect(span?.className).toContain('text-rose-600')
  })

  it('renders dot by default', () => {
    const { container } = render(<StatusChip label="OK" tone="pos" />)
    const dot = container.querySelector('span > span')
    expect(dot).not.toBeNull()
    expect(dot?.className).toContain('rounded-full')
  })

  it('omits dot when dot=false', () => {
    const { container } = render(<StatusChip label="OK" tone="pos" dot={false} />)
    const dot = container.querySelector('span > span')
    expect(dot).toBeNull()
  })

  it('exposes a class for every tone', () => {
    for (const tone of ['pos', 'neg', 'warn', 'info', 'muted'] as const) {
      expect(TONE_CLASSES[tone].chip).toBeTruthy()
    }
  })
})
