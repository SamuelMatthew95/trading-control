import { describe, it, expect } from 'vitest'

import { appendEquitySample } from '@/hooks/useLiveEquitySeries'

describe('appendEquitySample', () => {
  it('seeds the first point from a zero baseline (delta equals the total)', () => {
    const series = appendEquitySample([], -1.06, 1000)
    expect(series).toHaveLength(1)
    expect(series[0].equity).toBe(-1.06)
    expect(series[0].delta).toBe(-1.06)
    expect(series[0].timestamp).toBe(1000)
  })

  it('computes delta as the move since the previous sample', () => {
    let series = appendEquitySample([], -1.0, 1000)
    series = appendEquitySample(series, -1.5, 4000)
    expect(series).toHaveLength(2)
    expect(series[1].equity).toBe(-1.5)
    expect(series[1].delta).toBeCloseTo(-0.5, 10)
  })

  it('caps the rolling window at maxPoints, dropping the oldest', () => {
    let series: ReturnType<typeof appendEquitySample> = []
    for (let i = 0; i < 5; i += 1) series = appendEquitySample(series, i, i * 1000, 3)
    expect(series).toHaveLength(3)
    expect(series.map((p) => p.equity)).toEqual([2, 3, 4])
  })
})
