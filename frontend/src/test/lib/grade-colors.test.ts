import { describe, it, expect } from 'vitest'

import { gradeBg, gradeTone, tierBadge, tierLabel } from '@/lib/grade-colors'

describe('grade-colors tier helpers', () => {
  it('labels tiers human-readably', () => {
    expect(tierLabel('PROMOTED')).toBe('Promoted')
    expect(tierLabel('UNDER_REVIEW')).toBe('Under Review')
    expect(tierLabel('UNRATED')).toBe('Unrated')
  })

  it('maps A+ to the same style as A', () => {
    expect(gradeBg('A+')).toBe(gradeBg('A'))
  })

  it('gradeTone maps each letter band to a distinct categorical hue', () => {
    expect(gradeTone('A+')).toContain('emerald')
    expect(gradeTone('B')).toContain('sky')
    expect(gradeTone('C-')).toContain('amber')
    expect(gradeTone('D')).toContain('orange')
    expect(gradeTone('F')).toContain('rose')
    expect(gradeTone('NR')).toContain('slate')
    expect(gradeTone(null)).toContain('slate')
    expect(gradeTone(undefined)).toContain('slate')
  })

  it('gives visually distinct badges for promoted vs under-review', () => {
    expect(tierBadge('PROMOTED')).not.toBe(tierBadge('UNDER_REVIEW'))
    expect(tierBadge('PROMOTED')).toContain('emerald')
    expect(tierBadge('UNDER_REVIEW')).toContain('rose')
  })

  it('falls back to a neutral badge for an unknown tier', () => {
    expect(tierBadge('SOMETHING_ELSE')).toContain('slate')
  })
})
