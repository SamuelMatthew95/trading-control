'use client'

import { useEffect, useRef, useCallback } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'

// Type definitions for production-grade safety
type WebSocketMessage = {
  type: 'dashboard_update' | 'system_metric' | 'event' | 'agent_event'
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
      // Remove all listeners to prevent ghosts BEFORE closing
      this.socket.onopen = null
      this.socket.onmessage = null
      this.socket.onclose = null
      this.socket.onerror = null
      
      // Close if not already closed
      if (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING) {
        try {
          this.socket.close(1000, 'Cleanup')
        } catch (error) {
          console.warn('Error closing WebSocket during cleanup:', error)
        }
      }
      
      this.socket = null
    }

    // Clear all timers to prevent memory leaks
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    
    if (this.connectionTimeout) {
      clearTimeout(this.connectionTimeout)
      this.connectionTimeout = null
    }
  }

  private normalizeAgentEvent(rawEvent: any): any | null {
    try {
      if (!rawEvent || typeof rawEvent !== 'object') {
        return null
      }

      return {
        agent_name: rawEvent.agent_name || rawEvent.agent || 'Unknown',
        event_type: this.normalizeEventType(rawEvent.event_type || rawEvent.action || rawEvent.type || 'processed'),
        timestamp: rawEvent.timestamp || rawEvent.created_at || new Date().toISOString(),
        symbol: rawEvent.symbol,
        action: rawEvent.action,
        latency_ms: Number(rawEvent.latency_ms) || 0,
        primary_edge: rawEvent.primary_edge,
        // Preserve other useful fields
        ...(rawEvent.stream && { stream: rawEvent.stream }),
        ...(rawEvent.message_id && { message_id: rawEvent.message_id }),
        ...(rawEvent.data && { data: rawEvent.data })
      }
    } catch (error) {
      console.warn('Error normalizing agent event:', error, rawEvent)
      return null
    }
  }

  private normalizeSystemMetric(rawMetric: any): any | null {
    try {
      if (!rawMetric || typeof rawMetric !== 'object') {
        return null
      }

      return {
        metric_name: rawMetric.metric_name || rawMetric.name || 'unknown',
        value: Number(rawMetric.value) || 0,
        timestamp: rawMetric.timestamp || rawMetric.created_at || new Date().toISOString(),
        labels: rawMetric.labels || {},
        // Preserve other useful fields
        ...(rawMetric.unit && { unit: rawMetric.unit }),
        ...(rawMetric.tags && { tags: rawMetric.tags })
      }
    } catch (error) {
      console.warn('Error normalizing system metric:', error, rawMetric)
      return null
    }
  }

  private normalizeEventType(eventType: string): string {
    if (!eventType || typeof eventType !== 'string') {
      return 'unknown'
    }

    // Standardize event types to prevent duplicates
    const eventTypeMap: Record<string, string> = {
      'buy': 'signal',
      'sell': 'signal', 
      'purchase': 'signal',
      'trade': 'signal',
      'order': 'signal',
      'execution': 'order',
      'execute': 'order',
      'fill': 'order',
      'market_tick': 'tick',
      'price_update': 'tick',
      'quote': 'tick',
      'analysis': 'analysis',
      'reasoning': 'analysis',
      'grading': 'grade',
      'assessment': 'grade',
      'learning': 'learning',
      'training': 'learning',
      'reflection': 'reflection',
      'review': 'reflection',
      'notification': 'notification',
      'alert': 'notification',
      'message': 'notification'
    }
    
    const normalized = eventTypeMap[eventType.toLowerCase()]
    return normalized || eventType.toLowerCase()
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
          
          // Process agent events from dashboard data
          if (payload.data.agent_logs) {
            payload.data.agent_logs.forEach((agentLog: any) => {
              const normalizedLog = this.normalizeAgentEvent(agentLog)
              if (normalizedLog) {
                store.addAgentLog(normalizedLog)
              }
            })
          }
          
          // Process system metrics from dashboard data
          if (payload.data.system_metrics) {
            payload.data.system_metrics.forEach((metric: any) => {
              const normalizedMetric = this.normalizeSystemMetric(metric)
              if (normalizedMetric) {
                store.addSystemMetric(normalizedMetric)
              }
            })
          }
          
        } else if (payload.type === 'system_metric' && payload.data) {
          const normalizedMetric = this.normalizeSystemMetric(payload.data)
          if (normalizedMetric) {
            store.addSystemMetric(normalizedMetric)
          }
        } else if (payload.type === 'agent_event' && payload.data) {
          // Handle individual agent events
          const normalizedLog = this.normalizeAgentEvent(payload.data)
          if (normalizedLog) {
            store.addAgentLog(normalizedLog)
            console.log('Agent event processed:', normalizedLog.agent_name)
          }
        } else if (payload.type === 'event' && payload.data) {
          console.log('Generic event received:', payload.stream, payload.data)
          // Try to process as agent event if it has agent info
          if (payload.data.agent_name || payload.data.agent) {
            const normalizedLog = this.normalizeAgentEvent(payload.data)
            if (normalizedLog) {
              store.addAgentLog(normalizedLog)
            }
          }
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
      console.log('Connection already in progress, skipping duplicate connect')
      return
    }

    // Cleanup any existing socket BEFORE creating new one
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

  // Static methods for easy access
  public static connect(): void {
    WebSocketManager.getInstance().connect()
  }

  public static disconnect(): void {
    WebSocketManager.getInstance().disconnect()
  }

  public static reconnect(): void {
    WebSocketManager.getInstance().reconnect()
  }

  public static isConnected(): boolean {
    return WebSocketManager.getInstance().isConnected()
  }

  public static getConnectionState(): ConnectionState {
    return WebSocketManager.getInstance().getConnectionState()
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
