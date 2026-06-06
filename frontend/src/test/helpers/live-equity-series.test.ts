import { describe, it, expect, beforeEach } from 'vitest'

import { appendEquitySample, loadPersistedEquitySeries } from '@/hooks/useLiveEquitySeries'

const STORAGE_KEY = 'codex.equityCurve'
const point = (timestamp: number, equity: number) => ({ timestamp, label: '', pnl: equity, delta: 0, equity })

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

describe('loadPersistedEquitySeries', () => {
  beforeEach(() => window.localStorage.clear())

  it('returns [] when nothing is stored', () => {
    expect(loadPersistedEquitySeries()).toEqual([])
  })

  it('returns [] for malformed JSON', () => {
    window.localStorage.setItem(STORAGE_KEY, 'not json{')
    expect(loadPersistedEquitySeries()).toEqual([])
  })

  it('restores recent points and drops stale (> 1h) ones', () => {
    const now = 10_000_000
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([point(now - 2 * 60 * 60 * 1000, -1), point(now - 1000, -1.15)]),
    )
    const restored = loadPersistedEquitySeries(now)
    expect(restored).toHaveLength(1)
    expect(restored[0].equity).toBe(-1.15)
  })

  it('ignores malformed entries', () => {
    const now = 10_000_000
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([{ nope: true }, point(now - 1000, 5), { timestamp: 'x', equity: 1 }]),
    )
    expect(loadPersistedEquitySeries(now)).toHaveLength(1)
  })

  it('starts fresh when the newest point is stale (avoids a fabricated reload jump)', () => {
    const now = 10_000_000
    // Both points are < 1h old but the newest is 4 min old — past the continuity
    // window, so grafting new live points would draw a misleading sloped segment.
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([point(now - 5 * 60 * 1000, -1), point(now - 4 * 60 * 1000, -1.1)]),
    )
    expect(loadPersistedEquitySeries(now)).toEqual([])
  })
})
