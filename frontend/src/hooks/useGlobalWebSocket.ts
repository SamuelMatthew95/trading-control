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
  get isConnected() {
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
      
      // Dispatch events for React components to handle
      // This prevents invalid hook calls outside React components
      const eventPayload = msg.data ?? (msg as unknown as { payload?: unknown }).payload
      
      if (msg.type === 'dashboard_update' && msg.data) {
        this.dispatch('dashboard-update', { data: msg.data })
      } else if (msg.type === 'system_metric' && eventPayload) {
        this.dispatch('system-metric', { data: eventPayload })
      } else if (msg.stream === 'market_ticks') {
        const price = Number(msg.price)
        const symbol = msg.symbol || 'UNKNOWN'
        if (Number.isFinite(price)) {
          this.dispatch('price-update', { symbol, price })
        }
      } else if (msg.type === 'price_update' && msg.symbol && msg.price) {
        const price = Number(msg.price)
        const symbol = msg.symbol
        const timestamp = msg.timestamp || new Date().toISOString()
        if (Number.isFinite(price)) {
          this.dispatch('price-update', { symbol, price, timestamp })
        }
      } else if (msg.stream === 'signals') {
        this.dispatch('signal-received', { data: msg })
      } else if (msg.stream === 'orders') {
        this.dispatch('order-update', { data: msg })
      } else if (msg.stream === 'notifications') {
        this.dispatch('notification-received', { data: msg })
      } else if ((msg.type === 'agent_event' || msg.type === 'agent_status') && eventPayload) {
        this.dispatch('agent-event', { data: eventPayload })
      } else if (msg.type === 'event' && eventPayload) {
        this.dispatch('system-event', { data: eventPayload })
      } else if (msg.stream === 'agent_logs') {
        this.dispatch('agent-logs', { data: msg })
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
}

// --- Hook ---
export function useGlobalWebSocket() {
  const setWsConnected = useCodexStore((state) => state.setWsConnected)
  const wsConnected = useCodexStore((state) => state.wsConnected)
  const manager = WebSocketManager.instance
  const initialized = useRef(false)

  // Provide store update fn to manager for reactive state
  useEffect(() => {
    const isConnected = manager.isConnected
    manager.setStoreUpdate(() => setWsConnected(isConnected))
    return () => { manager.setStoreUpdate(null) }
  }, [setWsConnected, manager])

  useEffect(() => {
    if (initialized.current) return
    initialized.current = true
    if (typeof window === 'undefined') return
    // Connect if not connected
    if (!manager.isConnected) manager.connect()
    // Event listeners for UI reactivity (store is primary, but also for redundancy)
    const onConnect = () => setWsConnected(true)
    const onDisconnect = () => setWsConnected(false)
    manager.addEventListener('ws-connected', onConnect)
    manager.addEventListener('ws-disconnected', onDisconnect)
    return () => {
      manager.removeEventListener('ws-connected', onConnect)
      manager.removeEventListener('ws-disconnected', onDisconnect)
    }
  }, [setWsConnected, manager])

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
