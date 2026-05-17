import { describe, it, expect } from 'vitest'
import { deriveActivityIndicator } from '@/lib/agent-activity'

const NOW = new Date('2026-05-17T12:00:00.000Z').getTime()
const FRESH_MS = 60_000

describe('deriveActivityIndicator', () => {
  it('returns LIVE for a timestamp within the freshness window', () => {
    const ts = new Date(NOW - 30_000).toISOString() // 30 s ago
    expect(deriveActivityIndicator(ts, true, FRESH_MS, NOW)).toBe('live')
    expect(deriveActivityIndicator(ts, false, FRESH_MS, NOW)).toBe('live')
  })

  it('returns LIVE for a timestamp exactly at the boundary (exclusive)', () => {
    const ts = new Date(NOW - FRESH_MS + 1).toISOString()
    expect(deriveActivityIndicator(ts, true, FRESH_MS, NOW)).toBe('live')
  })

  it('returns WAITING for a stale timestamp when ws is connected', () => {
    const ts = new Date(NOW - FRESH_MS).toISOString() // exactly at threshold → stale
    expect(deriveActivityIndicator(ts, true, FRESH_MS, NOW)).toBe('waiting')
  })

  it('returns OFFLINE for a stale timestamp when ws is disconnected', () => {
    const ts = new Date(NOW - FRESH_MS).toISOString()
    expect(deriveActivityIndicator(ts, false, FRESH_MS, NOW)).toBe('offline')
  })

  it('returns WAITING when timestamp is null and ws is connected', () => {
    expect(deriveActivityIndicator(null, true, FRESH_MS, NOW)).toBe('waiting')
  })

  it('returns OFFLINE when timestamp is null and ws is disconnected', () => {
    expect(deriveActivityIndicator(null, false, FRESH_MS, NOW)).toBe('offline')
  })

  it('returns WAITING when timestamp is undefined and ws is connected', () => {
    expect(deriveActivityIndicator(undefined, true, FRESH_MS, NOW)).toBe('waiting')
  })

  it('ignores malformed timestamp strings (falls through to ws check)', () => {
    expect(deriveActivityIndicator('not-a-date', true, FRESH_MS, NOW)).toBe('waiting')
    expect(deriveActivityIndicator('not-a-date', false, FRESH_MS, NOW)).toBe('offline')
  })

  it('uses custom freshness threshold', () => {
    const ts = new Date(NOW - 5_000).toISOString() // 5 s ago
    expect(deriveActivityIndicator(ts, false, 3_000, NOW)).toBe('offline') // 5 s > 3 s threshold
    expect(deriveActivityIndicator(ts, false, 10_000, NOW)).toBe('live')   // 5 s < 10 s threshold
  })
})
