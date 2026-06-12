import { describe, expect, it } from 'vitest'

import { actionTone, signed, statusTone } from '@/lib/cognitive'

describe('cognitive helpers', () => {
  it('actionTone distinguishes buy / sell / hold via the Tone tokens', () => {
    expect(actionTone('buy')).toContain('success')
    expect(actionTone('sell')).toContain('danger')
    expect(actionTone('hold')).toContain('muted')
  })

  it('statusTone reflects proposal lifecycle via the Tone tokens', () => {
    expect(statusTone('approved')).toContain('success')
    expect(statusTone('merged')).toContain('success')
    expect(statusTone('rejected')).toContain('danger')
    expect(statusTone('backtesting')).toContain('warning')
    expect(statusTone('generated')).toContain('muted')
  })

  it('signed formats numbers with an explicit sign', () => {
    expect(signed(0.18)).toBe('+0.18')
    expect(signed(-1.2)).toBe('-1.20')
    expect(signed(0.5, 3)).toBe('+0.500')
    expect(signed(null)).toBe('--')
    expect(signed(undefined)).toBe('--')
  })
})
