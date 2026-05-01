import { useCodexStore } from '@/stores/useCodexStore'

describe('notifications store', () => {
  beforeEach(() => {
    useCodexStore.setState({ notifications: [] })
  })

  it('adds ui-ready notifications without frontend filtering', () => {
    useCodexStore.getState().addNotification({
      severity: 'info',
      message: 'hello',
      notification_type: 'stream:agent_logs',
      id: 'n1',
      timestamp: new Date().toISOString(),
    })
    expect(useCodexStore.getState().notifications).toHaveLength(1)
  })

  it('hydrates body-only ui contract payloads', () => {
    useCodexStore.getState().addNotification({
      severity: 'success',
      body: 'Bought 0.5 BTC @ 64000 USD',
      notification_type: 'trade.buy_filled',
      id: 'n2',
      timestamp: new Date().toISOString(),
    } as never)
    const [item] = useCodexStore.getState().notifications
    expect(item.message).toContain('Bought 0.5 BTC')
  })

  it('uses deterministic fallback id when backend id is missing', () => {
    const timestamp = new Date().toISOString()
    useCodexStore.getState().addNotification({
      severity: 'info',
      message: 'same payload',
      notification_type: 'trade.buy_filled',
      timestamp,
      symbol: 'AAPL',
      action: 'buy',
    } as never)
    useCodexStore.getState().addNotification({
      severity: 'info',
      message: 'same payload',
      notification_type: 'trade.buy_filled',
      timestamp,
      symbol: 'AAPL',
      action: 'buy',
    } as never)
    const list = useCodexStore.getState().notifications
    expect(list).toHaveLength(1)
    expect(list[0].id).toMatch(/^\d+-/)
  })
})
