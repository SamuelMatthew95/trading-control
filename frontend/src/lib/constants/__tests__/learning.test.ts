import { describe, it, expect } from 'vitest'
import {
  FALLBACK_LABELS,
  FALLBACK_MESSAGES,
  FALLBACK_UNKNOWN_LABEL,
  PROPOSAL_TYPE_LABEL,
  PROPOSAL_TYPE_TONE,
  PIPELINE_FRESH_WINDOW_MS,
  STREAM_LIVE_WINDOW_MS,
  PIPELINE_STREAM_NAMES,
  RECENT_EVENT_TONE,
  SHARPE_GREAT_THRESHOLD,
  SHARPE_NEUTRAL_THRESHOLD,
} from '../learning'

describe('learning constants', () => {
  it('every fallback mode has a label', () => {
    for (const mode of ['skip_reasoning', 'reject_signal', 'use_last_reflection']) {
      expect(FALLBACK_LABELS[mode]).toBeTruthy()
    }
  })

  it('FALLBACK_MESSAGES contains every translated label plus the unknown label', () => {
    for (const label of Object.values(FALLBACK_LABELS)) {
      expect(FALLBACK_MESSAGES.has(label)).toBe(true)
    }
    expect(FALLBACK_MESSAGES.has(FALLBACK_UNKNOWN_LABEL)).toBe(true)
  })

  it('every proposal type has a label and a tone', () => {
    const labelKeys = Object.keys(PROPOSAL_TYPE_LABEL).sort()
    const toneKeys = Object.keys(PROPOSAL_TYPE_TONE).sort()
    expect(labelKeys).toEqual(toneKeys)
  })

  it('thresholds are positive numbers', () => {
    expect(PIPELINE_FRESH_WINDOW_MS).toBeGreaterThan(0)
    expect(STREAM_LIVE_WINDOW_MS).toBeGreaterThan(0)
  })

  it('Sharpe thresholds are ordered correctly', () => {
    expect(SHARPE_GREAT_THRESHOLD).toBeGreaterThan(SHARPE_NEUTRAL_THRESHOLD)
  })

  it('PIPELINE_STREAM_NAMES is non-empty', () => {
    expect(PIPELINE_STREAM_NAMES.length).toBeGreaterThan(0)
    // Sanity check: each name is a recognizable stream from the backend.
    expect(PIPELINE_STREAM_NAMES).toContain('signals')
    expect(PIPELINE_STREAM_NAMES).toContain('orders')
  })

  it('RECENT_EVENT_TONE only contains valid tones', () => {
    const validTones = new Set(['pos', 'neg', 'warn', 'info', 'muted'])
    for (const tone of Object.values(RECENT_EVENT_TONE)) {
      expect(validTones.has(tone)).toBe(true)
    }
  })
})
