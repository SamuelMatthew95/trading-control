'use client'

import { useMemo } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'

export type SystemStatus = 'booting' | 'idle' | 'trading' | 'error'

/**
 * Single source of truth for the System Status badge that appears in BOTH the
 * dashboard layout header chip and the per-section banner. Without this, each
 * computation diverged on its own dependency set and produced contradictory
 * states across pages (e.g. Overview = IDLE while Agents = BOOTING).
 */
export function useSystemStatus(): SystemStatus {
  const wsConnected = useCodexStore((s) => s.wsConnected)
  const ordersLen = useCodexStore((s) => s.orders.length)
  const positionsLen = useCodexStore((s) => s.positions.length)
  const tradeFeedLen = useCodexStore((s) => s.tradeFeed.length)

  return useMemo<SystemStatus>(() => {
    if (!wsConnected) return 'booting'
    if (ordersLen > 0 || positionsLen > 0 || tradeFeedLen > 0) return 'trading'
    return 'idle'
  }, [wsConnected, ordersLen, positionsLen, tradeFeedLen])
}
