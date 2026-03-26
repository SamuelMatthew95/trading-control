'use client'

import { useEffect, useRef, useCallback } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'

// Type definitions for production-grade safety
type WebSocketMessage = {
  type: 'dashboard_update' | 'system_metric' | 'event'
  schema_version: string
  timestamp: string
  data: any
  stream?: string
  message_id?: string
}

type CustomEventDetail = {
  detail: WebSocketMessage
}

// WebSocket client wrapper - production grade singleton
let globalSocket: WebSocket | null = null
let globalRetryCount = 0
let isConnecting = false
const MAX_RETRIES = 5
const BASE_DELAY = 2000
const MAX_DELAY = 30000

function getWsUrl(): string {
  if (typeof window === 'undefined') return ''
  const base = process.env.NEXT_PUBLIC_WS_URL || window.location.origin
  return `${base.replace(/\/$/, '')}/ws/dashboard`
}

// Exponential backoff with jitter
function getRetryDelay(attempt: number): number {
  const delay = Math.min(BASE_DELAY * Math.pow(2, attempt), MAX_DELAY)
  // Add jitter to prevent thundering herd
  return delay + Math.random() * 1000
}

// Production-grade connection with cleanup
function connectWebSocket(): void {
  // SSR safety
  if (typeof window === 'undefined' || isConnecting) return
  
  if (globalSocket?.readyState === WebSocket.OPEN) {
    return
  }

  isConnecting = true
  
  try {
    // Cleanup any existing handlers to prevent ghosts
    if (globalSocket) {
      globalSocket.onopen = null
      globalSocket.onmessage = null
      globalSocket.onclose = null
      globalSocket.onerror = null
    }
    
    globalSocket = new WebSocket(getWsUrl())
    
    globalSocket.onopen = () => {
      console.log('WebSocket connected')
      globalRetryCount = 0
      isConnecting = false
      
      // Get fresh store state to avoid stale closures
      const store = useCodexStore.getState()
      store.setWsConnected(true)
      
      window.dispatchEvent(new CustomEvent('ws-connected'))
    }

    globalSocket.onmessage = (event) => {
      try {
        // Explicit error boundary for JSON parsing
        const payload: WebSocketMessage = JSON.parse(event.data)
        console.log('WebSocket message received:', payload)
        
        // Dispatch with strict typing
        window.dispatchEvent(new CustomEvent('ws-message', {
          detail: payload
        } as CustomEventDetail))
        
        // CRITICAL: Get fresh store state on every message to prevent stale closures
        const store = useCodexStore.getState()
        
        if (payload.type === 'dashboard_update' && payload.data) {
          console.log('Dashboard update received:', payload.data)
          
          // Single bulk update to prevent re-render thrashing
          store.hydrateDashboard(payload.data)
        } else if (payload.type === 'system_metric' && payload.data) {
          store.addSystemMetric(payload.data)
        } else if (payload.type === 'event' && payload.data) {
          console.log('Event received:', payload.stream, payload.data)
        }
        
      } catch (error) {
        console.error('WebSocket message parsing error:', error)
        // Continue processing other messages even if one fails
      }
    }

    globalSocket.onclose = (event) => {
      console.log('WebSocket disconnected:', event.code, event.reason)
      globalSocket = null
      isConnecting = false
      
      // Update store state
      useCodexStore.getState().setWsConnected(false)
      
      window.dispatchEvent(new CustomEvent('ws-disconnected'))
      
      // Improved reconnection resilience
      if (globalRetryCount < MAX_RETRIES && !event.wasClean) {
        globalRetryCount++
        const delay = getRetryDelay(globalRetryCount)
        console.log(`Reconnecting in ${delay}ms (attempt ${globalRetryCount})`)
        setTimeout(connectWebSocket, delay)
      }
    }

    globalSocket.onerror = (error) => {
      console.error('WebSocket error:', error)
      isConnecting = false
      useCodexStore.getState().setWsConnected(false)
    }
    
  } catch (error) {
    console.error('Failed to connect WebSocket:', error)
    isConnecting = false
    useCodexStore.getState().setWsConnected(false)
  }
}

// Production-grade hook with proper cleanup
export function useGlobalWebSocket() {
  const { setWsConnected, wsConnected } = useCodexStore()
  const initializedRef = useRef(false)
  const cleanupRef = useRef<(() => void) | null>(null)

  const cleanup = useCallback(() => {
    if (cleanupRef.current) {
      cleanupRef.current()
      cleanupRef.current = null
    }
  }, [])

  useEffect(() => {
    // SSR safety + prevent multiple initializations
    if (!initializedRef.current && typeof window !== 'undefined') {
      initializedRef.current = true
      connectWebSocket()
      
      // Setup event listeners with proper cleanup
      const handleConnected = () => setWsConnected(true)
      const handleDisconnected = () => setWsConnected(false)
      
      window.addEventListener('ws-connected', handleConnected)
      window.addEventListener('ws-disconnected', handleDisconnected)
      
      cleanupRef.current = () => {
        window.removeEventListener('ws-connected', handleConnected)
        window.removeEventListener('ws-disconnected', handleDisconnected)
      }
    }

    return cleanup
  }, [setWsConnected, cleanup])

  // Cleanup on unmount
  useEffect(() => {
    return cleanup
  }, [cleanup])

  return {
    socket: globalSocket,
    // IMPORTANT: Use reactive state from store, not calculated value
    // This ensures UI re-renders when connection state changes
    isConnected: wsConnected,
    reconnect: () => connectWebSocket()
  }
}
