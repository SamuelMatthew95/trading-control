import { describe, expect, it } from 'vitest'

import { actionTone, gradeTone, signed, statusTone } from '@/lib/cognitive'

describe('cognitive helpers', () => {
  it('gradeTone maps each letter band to a distinct tone', () => {
    expect(gradeTone('A+')).toContain('emerald')
    expect(gradeTone('B')).toContain('sky')
    expect(gradeTone('C-')).toContain('amber')
    expect(gradeTone('D')).toContain('orange')
    expect(gradeTone('F')).toContain('rose')
    expect(gradeTone('NR')).toContain('slate')
    expect(gradeTone(null)).toContain('slate')
    expect(gradeTone(undefined)).toContain('slate')
  })

  it('actionTone distinguishes buy / sell / hold', () => {
    expect(actionTone('buy')).toContain('emerald')
    expect(actionTone('sell')).toContain('rose')
    expect(actionTone('hold')).toContain('slate')
  })

  it('statusTone reflects proposal lifecycle', () => {
    expect(statusTone('approved')).toContain('emerald')
    expect(statusTone('merged')).toContain('emerald')
    expect(statusTone('rejected')).toContain('rose')
    expect(statusTone('backtesting')).toContain('amber')
    expect(statusTone('generated')).toContain('slate')
  })

  it('signed formats numbers with an explicit sign', () => {
    expect(signed(0.18)).toBe('+0.18')
    expect(signed(-1.2)).toBe('-1.20')
    expect(signed(0.5, 3)).toBe('+0.500')
    expect(signed(null)).toBe('—')
    expect(signed(undefined)).toBe('—')
  })
})
