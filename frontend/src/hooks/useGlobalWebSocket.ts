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

// Connection states for robust management
enum ConnectionState {
  DISCONNECTED = 'disconnected',
  CONNECTING = 'connecting', 
  CONNECTED = 'connected',
  RECONNECTING = 'reconnecting',
  ERROR = 'error'
}

// Bulletproof WebSocket Singleton Manager
class WebSocketManager {
  private static instance: WebSocketManager | null = null
  private socket: WebSocket | null = null
  private connectionState: ConnectionState = ConnectionState.DISCONNECTED
  private retryCount: number = 0
  private reconnectTimer: NodeJS.Timeout | null = null
  private connectionTimeout: NodeJS.Timeout | null = null
  private readonly MAX_RETRIES = 5
  private readonly BASE_DELAY = 2000
  private readonly MAX_DELAY = 30000
  private readonly CONNECTION_TIMEOUT = 10000
  private readonly RETRY_RESET_DELAY = 60000 // Reset retry count after 1 minute of connection

  private constructor() {
    // Private constructor for singleton
  }

  static getInstance(): WebSocketManager {
    if (!WebSocketManager.instance) {
      WebSocketManager.instance = new WebSocketManager()
    }
    return WebSocketManager.instance
  }

  private getWsUrl(): string {
    if (typeof window === 'undefined') return ''
    const base = process.env.NEXT_PUBLIC_WS_URL || window.location.origin
    return `${base.replace(/\/$/, '')}/ws/dashboard`
  }

  private getRetryDelay(attempt: number): number {
    const delay = Math.min(this.BASE_DELAY * Math.pow(2, attempt), this.MAX_DELAY)
    // Add jitter to prevent thundering herd
    return delay + Math.random() * 1000
  }

  private updateStoreState(): void {
    try {
      const store = useCodexStore.getState()
      store.setWsConnected(this.connectionState === ConnectionState.CONNECTED)
    } catch (error) {
      // Store might not be available during SSR
      console.warn('Could not update store state:', error)
    }
  }

  private cleanupSocket(): void {
    if (this.socket) {
      // Remove all listeners to prevent ghosts
      this.socket.onopen = null
      this.socket.onmessage = null
      this.socket.onclose = null
      this.socket.onerror = null
      
      // Close if not already closed
      if (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING) {
        this.socket.close(1000, 'Cleanup')
      }
      
      this.socket = null
    }

    // Clear timers
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    
    if (this.connectionTimeout) {
      clearTimeout(this.connectionTimeout)
      this.connectionTimeout = null
    }
  }

  private setupSocket(): void {
    if (!this.socket) return

    this.socket.onopen = () => {
      console.log('WebSocket connected')
      this.connectionState = ConnectionState.CONNECTED
      this.retryCount = 0 // Reset retry count on successful connection
      
      // Clear connection timeout
      if (this.connectionTimeout) {
        clearTimeout(this.connectionTimeout)
        this.connectionTimeout = null
      }

      this.updateStoreState()
      window.dispatchEvent(new CustomEvent('ws-connected'))
      
      // Reset retry count after successful connection
      setTimeout(() => {
        if (this.connectionState === ConnectionState.CONNECTED) {
          this.retryCount = 0
        }
      }, this.RETRY_RESET_DELAY)
    }

    this.socket.onmessage = (event) => {
      try {
        // Explicit error boundary for JSON parsing
        const payload: WebSocketMessage = JSON.parse(event.data)
        console.log('WebSocket message received:', payload)
        
        // Dispatch with proper typing
        window.dispatchEvent(new CustomEvent('ws-message', { 
          detail: payload 
        }))
        
        // Get fresh store state to prevent stale closures
        const store = useCodexStore.getState()
        
        if (payload.type === 'dashboard_update' && payload.data) {
          console.log('Dashboard update received:', payload.data)
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

    this.socket.onclose = (event) => {
      console.log('WebSocket disconnected:', event.code, event.reason)
      
      const wasConnected = this.connectionState === ConnectionState.CONNECTED
      this.connectionState = ConnectionState.DISCONNECTED
      
      this.cleanupSocket()
      this.updateStoreState()
      
      window.dispatchEvent(new CustomEvent('ws-disconnected'))

      // Reconnection logic with improved conditions
      if (wasConnected && this.retryCount < this.MAX_RETRIES) {
        this.connectionState = ConnectionState.RECONNECTING
        this.retryCount++
        
        const delay = this.getRetryDelay(this.retryCount)
        console.log(`Reconnecting in ${delay}ms (attempt ${this.retryCount}/${this.MAX_RETRIES})`)
        
        this.reconnectTimer = setTimeout(() => {
          this.connect()
        }, delay)
      } else if (this.retryCount >= this.MAX_RETRIES) {
        this.connectionState = ConnectionState.ERROR
        console.error('Max reconnection attempts reached')
      }
    }

    this.socket.onerror = (error) => {
      console.error('WebSocket error:', error)
      
      if (this.connectionState === ConnectionState.CONNECTING) {
        this.connectionState = ConnectionState.ERROR
        this.updateStoreState()
      }
    }
  }

  public connect(): void {
    // SSR safety
    if (typeof window === 'undefined') return

    // Prevent duplicate connections
    if (this.connectionState === ConnectionState.CONNECTING || 
        this.connectionState === ConnectionState.CONNECTED ||
        this.connectionState === ConnectionState.RECONNECTING) {
      return
    }

    // Cleanup any existing socket
    this.cleanupSocket()

    try {
      this.connectionState = ConnectionState.CONNECTING
      const url = this.getWsUrl()
      
      console.log('Connecting to WebSocket:', url)
      this.socket = new WebSocket(url)

      // Set connection timeout
      this.connectionTimeout = setTimeout(() => {
        if (this.connectionState === ConnectionState.CONNECTING) {
          console.error('WebSocket connection timeout')
          this.cleanupSocket()
          this.connectionState = ConnectionState.ERROR
          this.updateStoreState()
        }
      }, this.CONNECTION_TIMEOUT)

      this.setupSocket()
      this.updateStoreState()

    } catch (error) {
      console.error('Failed to create WebSocket:', error)
      this.connectionState = ConnectionState.ERROR
      this.updateStoreState()
    }
  }

  public disconnect(): void {
    console.log('Manual WebSocket disconnect requested')
    this.cleanupSocket()
    this.connectionState = ConnectionState.DISCONNECTED
    this.retryCount = 0
    this.updateStoreState()
  }

  public reconnect(): void {
    console.log('Manual reconnection requested')
    this.retryCount = 0 // Reset retry count for manual reconnection
    this.connect()
  }

  public getConnectionState(): ConnectionState {
    return this.connectionState
  }

  public isConnected(): boolean {
    return this.connectionState === ConnectionState.CONNECTED && 
           this.socket?.readyState === WebSocket.OPEN
  }

  public getSocket(): WebSocket | null {
    return this.socket
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
      
      // Get singleton manager instance
      const manager = WebSocketManager.getInstance()
      
      // Connect if not already connected
      if (!manager.isConnected()) {
        manager.connect()
      }
      
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
    socket: WebSocketManager.getInstance().getSocket(),
    // IMPORTANT: Use reactive state from store, not calculated value
    // This ensures UI re-renders when connection state changes
    isConnected: wsConnected,
    connectionState: WebSocketManager.getInstance().getConnectionState(),
    reconnect: () => WebSocketManager.getInstance().reconnect(),
    disconnect: () => WebSocketManager.getInstance().disconnect()
  }
}
