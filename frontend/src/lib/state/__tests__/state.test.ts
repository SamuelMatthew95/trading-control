import { describe, it, expect } from 'vitest'
import {
  TONE_CLASSES,
  getNumberTone,
  toneForAgentStatus,
  pickHigherPriorityStatus,
  toneForGrade,
  toneForScore,
  toneForRatio,
  toneForTradeSide,
  toneForOrderStatus,
  isClosedTrade,
} from '../index'

describe('TONE_CLASSES', () => {
  it('exposes a class set for every tone', () => {
    for (const tone of ['pos', 'neg', 'warn', 'info', 'muted'] as const) {
      const c = TONE_CLASSES[tone]
      expect(c.text).toBeTruthy()
      expect(c.bg).toBeTruthy()
      expect(c.chip).toBeTruthy()
      expect(c.card).toBeTruthy()
    }
  })
})

describe('getNumberTone', () => {
  it('positive → pos', () => expect(getNumberTone(1)).toBe('pos'))
  it('negative → neg', () => expect(getNumberTone(-1)).toBe('neg'))
  it('zero → muted', () => expect(getNumberTone(0)).toBe('muted'))
  it('null → muted', () => expect(getNumberTone(null)).toBe('muted'))
  it('NaN → muted', () => expect(getNumberTone(NaN)).toBe('muted'))
})

describe('toneForAgentStatus', () => {
  it('Live → pos', () => expect(toneForAgentStatus('Live')).toBe('pos'))
  it('Stale → warn', () => expect(toneForAgentStatus('Stale')).toBe('warn'))
  it('Error → neg', () => expect(toneForAgentStatus('Error')).toBe('neg'))
  it('Idle → muted', () => expect(toneForAgentStatus('Idle')).toBe('muted'))
})

describe('pickHigherPriorityStatus', () => {
  it('Live wins over Stale', () => {
    expect(pickHigherPriorityStatus('Stale', 'Live')).toBe('Live')
  })
  it('Live wins over everything', () => {
    expect(pickHigherPriorityStatus('Idle', 'Live')).toBe('Live')
    expect(pickHigherPriorityStatus('Error', 'Live')).toBe('Live')
  })
  it('returns incoming if current undefined', () => {
    expect(pickHigherPriorityStatus(undefined, 'Stale')).toBe('Stale')
  })
  it('keeps current if incoming is lower priority', () => {
    expect(pickHigherPriorityStatus('Live', 'Stale')).toBe('Live')
  })
})

describe('toneForGrade', () => {
  it('A and B map to pos', () => {
    expect(toneForGrade('A')).toBe('pos')
    expect(toneForGrade('B')).toBe('pos')
  })
  it('C maps to warn', () => expect(toneForGrade('C')).toBe('warn'))
  it('D and F map to neg', () => {
    expect(toneForGrade('D')).toBe('neg')
    expect(toneForGrade('F')).toBe('neg')
  })
  it('null/unknown → muted', () => {
    expect(toneForGrade(null)).toBe('muted')
    expect(toneForGrade('Z')).toBe('muted')
  })
  it('case-insensitive', () => {
    expect(toneForGrade('a')).toBe('pos')
  })
})

describe('toneForScore (0-100)', () => {
  it('high score → pos', () => expect(toneForScore(85)).toBe('pos'))
  it('mid score → warn', () => expect(toneForScore(55)).toBe('warn'))
  it('low score → neg', () => expect(toneForScore(20)).toBe('neg'))
  it('null → muted', () => expect(toneForScore(null)).toBe('muted'))
})

describe('toneForRatio (0-1)', () => {
  it('high ratio → pos', () => expect(toneForRatio(0.85)).toBe('pos'))
  it('mid ratio → warn', () => expect(toneForRatio(0.6)).toBe('warn'))
  it('low ratio → neg', () => expect(toneForRatio(0.3)).toBe('neg'))
})

describe('toneForTradeSide', () => {
  it('buy/long → pos', () => {
    expect(toneForTradeSide('buy')).toBe('pos')
    expect(toneForTradeSide('long')).toBe('pos')
    expect(toneForTradeSide('LONG')).toBe('pos')
  })
  it('sell/short → neg', () => {
    expect(toneForTradeSide('sell')).toBe('neg')
    expect(toneForTradeSide('short')).toBe('neg')
  })
  it('unknown → muted', () => expect(toneForTradeSide('foo')).toBe('muted'))
})

describe('toneForOrderStatus', () => {
  it('FILLED → pos', () => expect(toneForOrderStatus('FILLED')).toBe('pos'))
  it('REJECTED/CANCELLED → neg', () => {
    expect(toneForOrderStatus('REJECTED')).toBe('neg')
    expect(toneForOrderStatus('CANCELLED')).toBe('neg')
  })
  it('PENDING → warn', () => expect(toneForOrderStatus('PENDING')).toBe('warn'))
  it('case-insensitive', () => expect(toneForOrderStatus('filled')).toBe('pos'))
})

describe('isClosedTrade', () => {
  it('detects status field', () => {
    expect(isClosedTrade({ status: 'filled' })).toBe(true)
    expect(isClosedTrade({ status: 'closed' })).toBe(true)
    expect(isClosedTrade({ status: 'pending' })).toBe(false)
  })
  it('detects filled_at', () => {
    expect(isClosedTrade({ filled_at: '2026-01-01T00:00:00Z' })).toBe(true)
  })
  it('null/undefined → false', () => {
    expect(isClosedTrade(null)).toBe(false)
    expect(isClosedTrade(undefined)).toBe(false)
    expect(isClosedTrade({})).toBe(false)
  })
})
