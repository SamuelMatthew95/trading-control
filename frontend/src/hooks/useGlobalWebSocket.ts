import '../styles/globals.css'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Trading Control Dashboard',
  description: 'Real-time trading system dashboard with WebSocket updates',
}

// WebSocket client wrapper - initializes once for the whole app
let globalSocket: WebSocket | null = null
let globalRetryCount = 0
const MAX_RETRIES = 5

function getWsUrl() {
  const base = process.env.NEXT_PUBLIC_WS_URL || (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000')
  return `${base.replace(/\/$/, '')}/ws/dashboard`
}

function connectWebSocket() {
  if (globalSocket?.readyState === WebSocket.OPEN) {
    return globalSocket
  }

  try {
    globalSocket = new WebSocket(getWsUrl())
    globalSocket.onopen = () => {
      console.log('WebSocket connected')
      globalRetryCount = 0
      // Trigger connection state update for all components
      window.dispatchEvent(new CustomEvent('ws-connected'))
    }

    globalSocket.onmessage = (event) => {
      const payload = JSON.parse(event.data)
      // Dispatch to all components via custom event
      window.dispatchEvent(new CustomEvent('ws-message', { detail: payload }))
    }

    globalSocket.onclose = () => {
      console.log('WebSocket disconnected')
      globalSocket = null
      // Trigger disconnection event
      window.dispatchEvent(new CustomEvent('ws-disconnected'))
      
      // Retry logic
      if (globalRetryCount < MAX_RETRIES) {
        globalRetryCount++
        setTimeout(connectWebSocket, 2000 * globalRetryCount)
      }
    }

    globalSocket.onerror = (error) => {
      console.error('WebSocket error:', error)
    }
  } catch (error) {
    console.error('Failed to connect WebSocket:', error)
  }
}

// Initialize WebSocket connection immediately
if (typeof window !== 'undefined') {
  connectWebSocket()
}

export function useGlobalWebSocket() {
  return {
    socket: globalSocket,
    isConnected: globalSocket?.readyState === WebSocket.OPEN,
    reconnect: () => connectWebSocket()
  }
}
