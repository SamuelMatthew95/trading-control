import { getPnlTone, getStateLabel, getStateTone, getTradeSideTone, UNKNOWN_TONE } from '@/lib/status/stateTone'

describe('state tone helpers', () => {
  test.each(['ACTIVE','DEGRADED','ERROR','OPEN','PENDING','FILLED','REJECTED','BUY','SELL'])('supports %s', (state) => {
    expect(getStateTone(state)).not.toBe(UNKNOWN_TONE)
  })

  test.each(['IDLE','OFFLINE','CLOSED'])('maps %s to neutral tone', (state) => {
    expect(getStateTone(state)).toBe(UNKNOWN_TONE)
  })

  test('unknown fallback', () => {
    expect(getStateTone('mystery')).toBe(UNKNOWN_TONE)
    expect(getStateLabel('')).toBe('UNKNOWN')
  })

  test('pnl tone and trade side tone', () => {
    expect(getPnlTone(1)).toBe(getStateTone('buy'))
    expect(getPnlTone(-1)).toBe(getStateTone('sell'))
    expect(getPnlTone(0)).toBe(UNKNOWN_TONE)
    expect(getTradeSideTone('BUY')).toBe(getStateTone('buy'))
  })
})
