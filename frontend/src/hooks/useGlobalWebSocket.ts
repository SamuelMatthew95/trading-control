'use client'

import { useEffect, useRef } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'

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
      useCodexStore.getState().setWsConnected(true)
      // Trigger connection state update for all components
      window.dispatchEvent(new CustomEvent('ws-connected'))
    }

    globalSocket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data)
        console.log('WebSocket message received:', payload)
        
        // Dispatch to all components via custom event
        window.dispatchEvent(new CustomEvent('ws-message', { detail: payload }))
        
        // Get store methods for this message handling
        const { setDashboardData, setLoading } = useCodexStore.getState()
        
        // Update store based on message type
        if (payload.type === 'dashboard_update' && payload.data) {
          console.log('Dashboard update received:', payload.data)
          
          // Explicit state transition: set loading to false only when valid data arrives
          setLoading(false)
          
          // Key mapping: target payload.data directly for clean object
          setDashboardData(payload.data)
          
          const data = payload.data
          
          // Update system metrics if present
          if (data.system_metrics) {
            data.system_metrics.forEach((metric: any) => {
              useCodexStore.getState().addSystemMetric(metric)
            })
          }
          
          // Update other data types as needed
          if (data.orders) {
            data.orders.forEach((order: any) => {
              useCodexStore.getState().updateOrder(order)
            })
          }
          
          if (data.agent_logs) {
            data.agent_logs.forEach((log: any) => {
              useCodexStore.getState().addAgentLog(log)
            })
          }
        }
        
        // Handle individual event types
        if (payload.type === 'system_metric' && payload.data) {
          useCodexStore.getState().addSystemMetric(payload.data)
        }
        
        if (payload.type === 'event' && payload.data) {
          // Handle other event types as needed
          console.log('Event received:', payload.stream, payload.data)
        }
        
      } catch (error) {
        console.error('Error parsing WebSocket message:', error)
      }
    }

    globalSocket.onclose = () => {
      console.log('WebSocket disconnected')
      globalSocket = null
      // Trigger disconnection event
      window.dispatchEvent(new CustomEvent('ws-disconnected'))
      
      // Update store connection state
      useCodexStore.getState().setWsConnected(false)
      
      // Retry logic
      if (globalRetryCount < MAX_RETRIES) {
        globalRetryCount++
        setTimeout(connectWebSocket, 2000 * globalRetryCount)
      }
    }

    globalSocket.onerror = (error) => {
      console.error('WebSocket error:', error)
      useCodexStore.getState().setWsConnected(false)
    }
    
  } catch (error) {
    console.error('Failed to connect WebSocket:', error)
    useCodexStore.getState().setWsConnected(false)
  }
}

export function useGlobalWebSocket() {
  const { setWsConnected, setDashboardData, setLoading } = useCodexStore()
  const initializedRef = useRef(false)

  useEffect(() => {
    if (!initializedRef.current && typeof window !== 'undefined') {
      initializedRef.current = true
      connectWebSocket()
    }

    // Listen for connection state events
    const handleConnected = () => setWsConnected(true)
    const handleDisconnected = () => setWsConnected(false)

    window.addEventListener('ws-connected', handleConnected)
    window.addEventListener('ws-disconnected', handleDisconnected)

    return () => {
      window.removeEventListener('ws-connected', handleConnected)
      window.removeEventListener('ws-disconnected', handleDisconnected)
    }
  }, [setWsConnected, setDashboardData, setLoading])

  return {
    socket: globalSocket,
    isConnected: globalSocket?.readyState === WebSocket.OPEN,
    reconnect: () => connectWebSocket()
  }
}
