import { formatDateTime } from '@/lib/format/date'
import { UI_FALLBACK } from '@/lib/constants/ui'

describe('date formatter', () => {
  test('returns fallback for invalid', () => {
    expect(formatDateTime(null)).toBe(UI_FALLBACK)
    expect(formatDateTime('bad-date')).toBe(UI_FALLBACK)
  })
})
