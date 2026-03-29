'use client'
import { useEffect, useRef } from 'react'
import { useCodexStore } from '@/stores/useCodexStore'

// --- Types ---
type WebSocketMessage = {
  type: string
  schema_version?: string
  timestamp?: string
// eslint-disable-next-line @typescript-eslint/no-explicit-any
  data?: any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload?: any
  stream?: string
  event_type?: string
  message_id?: string
  msg_id?: string
  symbol?: string
  price?: string | number
  side?: string
  confidence?: string | number
}

export enum ConnectionState {
  DISCONNECTED = 'disconnected',
  CONNECTING = 'connecting',
  CONNECTED = 'connected',
  RECONNECTING = 'reconnecting',
  ERROR = 'error',
}

type Listener = (event: CustomEvent) => void

// --- WebSocketManager Singleton ---
class WebSocketManager {
  private static _instance: WebSocketManager | null = null
  private _socket: WebSocket | null = null
  private _state: ConnectionState = ConnectionState.DISCONNECTED
  private _retry: number = 0
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private _connTimeout: ReturnType<typeof setTimeout> | null = null
  private readonly MAX_RETRIES = 8
  private readonly BASE_DELAY = 2000
  private readonly MAX_DELAY = 30000
  private readonly CONN_TIMEOUT = 10000
  private readonly RETRY_RESET_DELAY = 60000
  private _lastConnectAt: number = 0

  // Event listeners: eventName -> Set<Listener>
  private _listeners: Map<string, Set<Listener>> = new Map()
  private _storeUpdate: (() => void) | null = null

  private constructor() {}
  static get instance() {
    if (!this._instance) this._instance = new WebSocketManager()
    return this._instance
  }

  // --- Event Listener System ---
  addEventListener(event: string, listener: Listener) {
    if (!this._listeners.has(event)) this._listeners.set(event, new Set())
    const set = this._listeners.get(event)!
    set.add(listener)
    window.addEventListener(event, listener as EventListener)
  }
  removeEventListener(event: string, listener: Listener) {
    const set = this._listeners.get(event)
    if (set) {
      set.delete(listener)
      window.removeEventListener(event, listener as EventListener)
      if (set.size === 0) this._listeners.delete(event)
    }
  }
  removeAllEventListeners() {
    for (const [event, set] of Array.from(this._listeners.entries())) {
      for (const l of Array.from(set)) window.removeEventListener(event, l as EventListener)
    }
    this._listeners.clear()
  }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
  dispatch(event: string, detail?: any) {
    try {
      window.dispatchEvent(new CustomEvent(event, { detail }))
    } catch {}
  }

  // --- Public API ---
  get state() { return this._state }
  get socket() { return this._socket }
  isConnected() {
    return this._state === ConnectionState.CONNECTED && this._socket?.readyState === WebSocket.OPEN
  }
  connect() {
    if (typeof window === 'undefined') return
    if (
      this._state === ConnectionState.CONNECTING ||
      this._state === ConnectionState.CONNECTED ||
      this._state === ConnectionState.RECONNECTING
    ) return
    this._cleanupSocket()
    this._state = ConnectionState.CONNECTING
    this._updateStoreState()
    const url = this._getWsUrl()
    if (!url) {
      this._state = ConnectionState.ERROR
      this._updateStoreState()
      return
    }
    try {
      this._socket = new WebSocket(url)
      this._lastConnectAt = Date.now()
      this._setupSocketHandlers()
      this._connTimeout = setTimeout(() => {
        if (this._state === ConnectionState.CONNECTING) {
          this._state = ConnectionState.ERROR
          this._cleanupSocket()
          this._updateStoreState()
        }
      }, this.CONN_TIMEOUT)
    } catch {
      this._state = ConnectionState.ERROR
      this._updateStoreState()
    }
  }
  disconnect() {
    this._cleanupSocket()
    this.removeAllEventListeners()
    this._state = ConnectionState.DISCONNECTED
    this._retry = 0
    this._updateStoreState()
  }
  reconnect() {
    this._retry = 0
    this.connect()
  }
  setStoreUpdate(fn: (() => void) | null) {
    this._storeUpdate = fn
  }

  // --- Private methods ---
  private _getWsUrl(): string {
    if (typeof window === 'undefined') return ''
    let base = process.env.NEXT_PUBLIC_WS_URL || window.location.origin
    base = base.replace(/\/$/, '')
    return `${base}/ws/dashboard`
  }
  private _getRetryDelay(attempt: number): number {
    const d = Math.min(this.BASE_DELAY * Math.pow(2, attempt), this.MAX_DELAY)
    return Math.floor(d + Math.random() * 1000)
  }
  private _cleanupSocket() {
    if (this._socket) {
      this._socket.onopen = null
      this._socket.onmessage = null
      this._socket.onerror = null
      this._socket.onclose = null
      if (
        this._socket.readyState === WebSocket.OPEN ||
        this._socket.readyState === WebSocket.CONNECTING
      ) {
        try { this._socket.close(1000, 'Cleanup') } catch {}
      }
    }
    this._socket = null
    if (this._reconnectTimer) clearTimeout(this._reconnectTimer)
    this._reconnectTimer = null
    if (this._connTimeout) clearTimeout(this._connTimeout)
    this._connTimeout = null
  }
  private _updateStoreState() {
    if (this._storeUpdate) {
      try { this._storeUpdate() } catch {}
    }
  }
  private _setupSocketHandlers() {
    if (!this._socket) return
    this._socket.onopen = () => {
      this._state = ConnectionState.CONNECTED
      this._retry = 0
      if (this._connTimeout) clearTimeout(this._connTimeout)
      this._connTimeout = null
      this._updateStoreState()
      this.dispatch('ws-connected')
      setTimeout(() => {
        if (this._state === ConnectionState.CONNECTED) this._retry = 0
      }, this.RETRY_RESET_DELAY)
    }
    this._socket.onmessage = (event) => {
      let msg: WebSocketMessage | null = null
      try { msg = JSON.parse(event.data) } catch {}
      if (!msg) return
      this.dispatch('ws-message', msg)
      // Store logic with safe data normalization
      // Note: We can't call useCodexStore.getState() here as it's outside a component
      // The store will be updated through the event system instead
      const eventPayload = msg.data ?? (msg as unknown as { payload?: unknown }).payload
      if (msg.type === 'dashboard_update' && msg.data) {
        try {
          // Normalize data safely before passing to store
          // const normalizedData = this._normalizeDashboardData(msg.data)
          // Note: Store updates will be handled through the event system
          // store.hydrateDashboard(normalizedData)
        } catch (error) {
          console.error('Error hydrating dashboard:', error)
        }
        // Note: Store updates disabled for now to fix hook call issues
        // if (Array.isArray(msg.data.agent_logs)) {
        //   for (const log of msg.data.agent_logs) {
        //     const norm = this._normalizeAgentEvent(log)
        //     if (norm) null // Store disabled for now
        //   }
        // }
        // if (Array.isArray(msg.data.system_metrics)) {
        //   for (const metric of msg.data.system_metrics) {
        //     const norm = this._normalizeSystemMetric(metric)
        //     if (norm) null // Store disabled for now
        //   }
        // }
      } else if (msg.type === 'system_metric' && eventPayload) {
        // const norm = this._normalizeSystemMetric(eventPayload)
        // if (norm) null // Store disabled for now
      } else if (msg.stream === 'market_ticks') {
        // const price = Number(msg.price)
        // const symbol = msg.symbol || 'UNKNOWN'
        // Note: Store updates disabled for now
        // const previousPrice = store.prices[symbol]?.price ?? price
        // const change = Number.isFinite(price) ? price - previousPrice : 0
        // if (Number.isFinite(price)) store.updatePrice(symbol, price, change)
        // store.trackMarketTick(symbol)
      } else if (msg.type === 'price_update' && msg.symbol && msg.price) {
        // Handle price updates from background worker
        // const price = Number(msg.price)
        // const symbol = msg.symbol
        // Note: Store updates disabled for now
        // const currentPriceData = store.prices[symbol]
        // const messageTimestamp = msg.timestamp || new Date().toISOString()
        
        // Only update if WebSocket data is newer than existing data
        // const shouldUpdate = !currentPriceData?.updatedAt || 
        //   new Date(messageTimestamp) > new Date(currentPriceData.updatedAt)
        
        // if (shouldUpdate && Number.isFinite(price)) {
        //   const previousPrice = currentPriceData?.price ?? price
        //   const change = price - previousPrice
        //   store.updatePrice(symbol, price, change)
        //   store.trackMarketTick(symbol)
        // }
      } else if (msg.stream === 'signals') {
        null // Store disabled for now
        // store.addSignal({
        //   ...(msg as unknown as Record<string, unknown>),
        //   confidence: Number(msg.confidence),
        // })
      } else if (msg.stream === 'orders') {
        null // Store disabled for now
        // Stream payloads are partially typed; store merge handles sparse updates.
        // store.updateOrder(msg as never)
      } else if (msg.stream === 'notifications') {
        null // Store disabled for now
        // store.addRiskAlert(msg as unknown as Record<string, unknown>)
      } else if ((msg.type === 'agent_event' || msg.type === 'agent_status') && eventPayload) {
        const normalizedAgentPayload = msg.type === 'agent_status'
          ? {
              agent_name: (eventPayload as Record<string, unknown>).name,
              timestamp: (eventPayload as Record<string, unknown>).updated_at || new Date().toISOString(),
              message: (eventPayload as Record<string, unknown>).last_task || 'status_update',
              ...(eventPayload as Record<string, unknown>),
            }
          : eventPayload
        const norm = this._normalizeAgentEvent(normalizedAgentPayload)
        if (norm) null // Store disabled for now
      } else if (msg.type === 'event' && eventPayload) {
        const unwrappedPayload = ((eventPayload as Record<string, unknown>).payload as Record<string, unknown> | undefined) ?? (eventPayload as Record<string, unknown>)
        const normalizedEventPayload = this._coerceObject(unwrappedPayload)
        if (!normalizedEventPayload) return
        
        const payloadWithContext: Record<string, unknown> = {
          ...normalizedEventPayload,
          stream: msg.stream || normalizedEventPayload.stream,
          event_type: msg.event_type || normalizedEventPayload.event_type,
          timestamp: msg.timestamp || normalizedEventPayload.timestamp,
        }

        const looksLikeAgentEvent = Boolean(
          payloadWithContext['agent_name'] ||
          payloadWithContext['agent'] ||
          payloadWithContext['stream'] === 'agent_logs' ||
          payloadWithContext['event_type'] === 'agent_log'
        )

        if (looksLikeAgentEvent) {
          const norm = this._normalizeAgentEvent(payloadWithContext)
          if (norm) null // Store disabled for now
        }
      } else if (msg.stream === 'agent_logs') {
        const source = msg as unknown as Record<string, unknown>
        const payloadObj = (source.payload as Record<string, unknown> | undefined) ?? {}
        const norm = this._normalizeAgentEvent({
          ...source,
          ...payloadObj,
          agent_name: source.agent || source.source || payloadObj.agent || source['agent_name'],
          timestamp: msg.timestamp || payloadObj.timestamp || new Date().toISOString(),
        })
        if (norm) null // Store disabled for now
      }
    }
    this._socket.onclose = (_event) => {
      const wasConnected = this._state === ConnectionState.CONNECTED
      this._state = ConnectionState.DISCONNECTED
      this._cleanupSocket()
      this._updateStoreState()
      this.dispatch('ws-disconnected')
      // Reconnect with exponential backoff + jitter
      if (wasConnected && this._retry < this.MAX_RETRIES) {
        this._state = ConnectionState.RECONNECTING
        this._retry++
        const delay = this._getRetryDelay(this._retry)
        this._reconnectTimer = setTimeout(() => this.connect(), delay)
      } else if (this._retry >= this.MAX_RETRIES) {
        this._state = ConnectionState.ERROR
        this._updateStoreState()
      }
    }
    this._socket.onerror = () => {
      if (this._state === ConnectionState.CONNECTING) {
        this._state = ConnectionState.ERROR
        this._updateStoreState()
      }
    }
  }

  // --- Normalization ---
// eslint-disable-next-line @typescript-eslint/no-explicit-any
  private _normalizeDashboardData(data: any): any {
    if (!data || typeof data !== 'object') return data
    
    const normalized = { ...data }
    
    // Normalize orders - handle both object and array formats
    if (normalized.orders && typeof normalized.orders === 'object' && !Array.isArray(normalized.orders)) {
      // Convert orders object to array format expected by store
      // Extract actual order arrays from the object
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      const ordersArray: any[] = []
      
      // Look for common order array keys
      const orderKeys = ['orders_last_hour', 'recent_orders', 'active_orders', 'pending_orders']
      for (const key of orderKeys) {
        const orderArray = normalized.orders[key]
        if (Array.isArray(orderArray)) {
          ordersArray.push(...orderArray)
        }
      }
      
      // If no arrays found, convert object values to array
      if (ordersArray.length === 0) {
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        const objectValues = Object.values(normalized.orders) as any[]
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        ordersArray.push(...objectValues.filter((item: any) => 
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          typeof item === 'object' && item !== null && !(item as any).timestamp // exclude metadata
        ))
      }
      
      normalized.orders = ordersArray
    } else if (!normalized.orders) {
      normalized.orders = []
    }
    
    // Normalize other array fields safely
    const arrayFields = ['agent_logs', 'system_metrics', 'signals', 'positions', 'risk_alerts', 'learning_events']
    for (const field of arrayFields) {
      if (normalized[field] && !Array.isArray(normalized[field])) {
        if (typeof normalized[field] === 'object') {
          // Convert object to array of values
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          const objectValues = Object.values(normalized[field]) as any[]
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          normalized[field] = objectValues.filter((item: any) => 
            typeof item === 'object' && item !== null
          )
        } else {
          // Set to empty array if not convertible
          normalized[field] = []
        }
      } else if (!normalized[field]) {
        normalized[field] = []
      }
    }
    
    return normalized
  }

// eslint-disable-next-line @typescript-eslint/no-explicit-any
  private _normalizeAgentEvent(raw: any): any | null {
    if (!raw || typeof raw !== 'object') return null
    const inferredAgentName = raw.agent_name || raw.agent || raw.source_agent || (raw.stream === 'agent_logs' ? 'Agent Pipeline' : 'Unknown')
    return {
      agent_name: inferredAgentName,
      event_type: this._normalizeEventType(raw.event_type || raw.action || raw.type || 'processed'),
      timestamp: raw.timestamp || raw.created_at || new Date().toISOString(),
      symbol: raw.symbol,
      action: raw.action,
      latency_ms: Number(raw.latency_ms) || 0,
      primary_edge: raw.primary_edge,
      ...(raw.stream && { stream: raw.stream }),
      ...(raw.message_id && { message_id: raw.message_id }),
      ...(raw.data && { data: raw.data }),
    }
  }

  private _coerceObject(value: unknown): Record<string, unknown> | null {
    if (!value) return null
    if (typeof value === 'object' && !Array.isArray(value)) {
      return value as Record<string, unknown>
    }
    if (typeof value === 'string') {
      try {
        const parsed = JSON.parse(value)
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          return parsed as Record<string, unknown>
        }
      } catch {
        return null
      }
    }
    return null
  }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
  private _normalizeSystemMetric(raw: any): any | null {
    if (!raw || typeof raw !== 'object') return null
    return {
      metric_name: raw.metric_name || raw.name || 'unknown',
      value: Number(raw.value) || 0,
      timestamp: raw.timestamp || raw.created_at || new Date().toISOString(),
      labels: raw.labels || {},
      ...(raw.unit && { unit: raw.unit }),
      ...(raw.tags && { tags: raw.tags }),
    }
  }
  private _normalizeEventType(val: string): string {
    if (!val || typeof val !== 'string') return 'unknown'
    const map: Record<string, string> = {
      buy: 'signal', sell: 'signal', purchase: 'signal', trade: 'signal', order: 'signal',
      execution: 'order', execute: 'order', fill: 'order',
      market_tick: 'tick', price_update: 'tick', quote: 'tick',
      analysis: 'analysis', reasoning: 'analysis',
      grading: 'grade', assessment: 'grade',
      learning: 'learning', training: 'learning',
      reflection: 'reflection', review: 'reflection',
      notification: 'notification', alert: 'notification', message: 'notification'
    }
    return map[val.toLowerCase()] || val.toLowerCase()
  }
}

// --- Hook ---
export function useGlobalWebSocket() {
  const setWsConnected = useCodexStore((state) => state.setWsConnected)
  const wsConnected = useCodexStore((state) => state.wsConnected)
  const manager = WebSocketManager.instance
  const initialized = useRef(false)

  // Provide store update fn to manager for reactive state
  useEffect(() => {
    manager.setStoreUpdate(() => setWsConnected(manager.isConnected()))
    return () => { manager.setStoreUpdate(null) }
    // eslint-disable-next-line
  }, [setWsConnected])

  useEffect(() => {
    if (initialized.current) return
    initialized.current = true
    if (typeof window === 'undefined') return
    // Connect if not connected
    if (!manager.isConnected()) manager.connect()
    // Event listeners for UI reactivity (store is primary, but also for redundancy)
    const onConnect = () => setWsConnected(true)
    const onDisconnect = () => setWsConnected(false)
    manager.addEventListener('ws-connected', onConnect)
    manager.addEventListener('ws-disconnected', onDisconnect)
    return () => {
      manager.removeEventListener('ws-connected', onConnect)
      manager.removeEventListener('ws-disconnected', onDisconnect)
    }
    // eslint-disable-next-line
  }, [setWsConnected])

  useEffect(() => {
    return () => {
      manager.removeAllEventListeners()
    }
  }, [manager])

  return {
    socket: manager.socket,
    isConnected: wsConnected,
    connectionState: manager.state,
    reconnect: () => manager.reconnect(),
    disconnect: () => manager.disconnect(),
  }
}
