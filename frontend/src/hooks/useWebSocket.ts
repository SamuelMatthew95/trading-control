'use client'

import { useGlobalWebSocket } from '@/hooks/useGlobalWebSocket'

export function useWebSocket() {
  return useGlobalWebSocket()
}
