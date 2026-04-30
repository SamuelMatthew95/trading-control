import { describe, expect, it } from 'vitest'
import { isDisplayableNotification } from '@/stores/useCodexStore'

describe('notification filtering', () => {
  it('rejects legacy raw stream notifications', () => {
    expect(
      isDisplayableNotification({
        notification_type: 'stream:agent_logs',
        stream_source: 'agent_logs',
        message: 'agent_logs:agent_log - hold',
      }),
    ).toBe(false)
    expect(
      isDisplayableNotification({
        notification_type: 'decision.hold',
        stream_source: 'decisions',
        message: 'DECISION - SPY | HOLD',
      }),
    ).toBe(false)
  })

  it('keeps current trade and agent notifications', () => {
    expect(
      isDisplayableNotification({
        notification_type: 'trade.buy_filled',
        stream_source: 'executions',
        message: 'BUY BTC/USD filled',
      }),
    ).toBe(true)
    expect(
      isDisplayableNotification({
        notification_type: 'proposal',
        stream_source: 'strategy_proposer',
        message: 'New parameter proposal',
      }),
    ).toBe(true)
  })
})
