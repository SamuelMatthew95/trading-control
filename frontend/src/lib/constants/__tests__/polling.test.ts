import { describe, it, expect } from 'vitest'
import {
  DASHBOARD_STATE_POLL_MS,
  DASHBOARD_DATA_POLL_MS,
  LLM_HEALTH_POLL_MS,
  SIGNALS_POLL_MS,
  LEARNING_DASHBOARD_POLL_MS,
} from '../polling'

describe('polling cadences', () => {
  it('all cadences are positive numbers', () => {
    expect(DASHBOARD_STATE_POLL_MS).toBeGreaterThan(0)
    expect(DASHBOARD_DATA_POLL_MS).toBeGreaterThan(0)
    expect(LLM_HEALTH_POLL_MS).toBeGreaterThan(0)
    expect(SIGNALS_POLL_MS).toBeGreaterThan(0)
    expect(LEARNING_DASHBOARD_POLL_MS).toBeGreaterThan(0)
  })

  it('LLM health polls more frequently than signals (operator-action sidebar)', () => {
    expect(LLM_HEALTH_POLL_MS).toBeLessThan(SIGNALS_POLL_MS)
  })

  it('dashboard state poll is more frequent than the steady-state data poll', () => {
    // The state poll only runs while the WebSocket is disconnected, so it
    // needs to be aggressive enough to recover quickly.
    expect(DASHBOARD_STATE_POLL_MS).toBeLessThanOrEqual(DASHBOARD_DATA_POLL_MS)
  })
})
