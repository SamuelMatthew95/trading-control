'use client'
import { useEffect, useRef } from 'react'
import {
  useDashboardStore,
  normalizeClosedTrade,
  normalizeTradeFeedItem,
  type AgentLog,
  type AgentHeartbeat,
  type DashboardData,
  type SystemMetric,
} from '@/stores/useDashboardStore'
import { coerceProposalContent, proposalStrategyName } from '@/lib/proposal-content'
import { createLogger } from '@/lib/logger'

const log = createLogger('WS')

// --- Types ---
type WebSocketMessage = {
  type: string
  schema_version?: string
  timestamp?: string
  data?: unknown
  payload?: unknown
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
  dispatch(event: string, detail?: unknown) {
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
    ) {
      log.debug('connect() skipped — already in state:', this._state)
      return
    }
    this._cleanupSocket()
    this._state = ConnectionState.CONNECTING
    this._updateStoreState()
    const url = this._getWsUrl()
    if (!url) {
      log.error('No URL resolved — cannot connect')
      this._state = ConnectionState.ERROR
      this._updateStoreState()
      return
    }
    log.info('Connecting to', url, '(attempt', this._retry + 1, ')')
    try {
      this._socket = new WebSocket(url)
      this._lastConnectAt = Date.now()
      this._setupSocketHandlers()
      this._connTimeout = setTimeout(() => {
        if (this._state === ConnectionState.CONNECTING) {
          log.error('Connection timed out after', this.CONN_TIMEOUT, 'ms →', url)
          this._state = ConnectionState.ERROR
          this._cleanupSocket()
          this._updateStoreState()
          // _cleanupSocket nulls onclose before close(), so onclose will not
          // fire to schedule a retry — kick the backoff loop here instead so
          // cold-start servers eventually get reached.
          this._scheduleReconnect()
        }
      }, this.CONN_TIMEOUT)
    } catch (err) {
      log.error('Failed to create WebSocket:', err)
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
    // connect() guards on RECONNECTING/CONNECTING/CONNECTED and bails out, so a
    // user-initiated reconnect from those states must clear it first.
    if (this._state === ConnectionState.RECONNECTING) {
      if (this._reconnectTimer) clearTimeout(this._reconnectTimer)
      this._reconnectTimer = null
      this._state = ConnectionState.DISCONNECTED
    }
    this.connect()
  }
  setStoreUpdate(fn: (() => void) | null) {
    this._storeUpdate = fn
  }

  // --- Private methods ---
  private _getWsUrl(): string {
    if (typeof window === 'undefined') return ''

    // 1. Explicit WS URL env var — always wins.
    const envUrl = process.env.NEXT_PUBLIC_WS_URL
    if (envUrl) {
      const wsBase = envUrl.replace(/^https:\/\//, 'wss://').replace(/^http:\/\//, 'ws://').replace(/\/$/, '')
      const url = `${wsBase}/ws/dashboard`
      log.info('URL source: NEXT_PUBLIC_WS_URL →', url)
      return url
    }

    // 2. Derive from the API base URL — handles the common case where only
    //    NEXT_PUBLIC_API_URL is set. Strip any trailing /api path segment so
    //    we end up at the service root (where /ws/dashboard lives).
    const apiUrl = process.env.NEXT_PUBLIC_API_URL
    if (apiUrl && /^https?:\/\//.test(apiUrl)) {
      const wsBase = apiUrl
        .replace(/\/api\/?$/, '')          // strip trailing /api
        .replace(/^https:\/\//, 'wss://')
        .replace(/^http:\/\//, 'ws://')
        .replace(/\/$/, '')
      const url = `${wsBase}/ws/dashboard`
      log.info('URL source: NEXT_PUBLIC_API_URL (derived) →', url)
      return url
    }

    // 3. Same-origin fallback — only correct in local development where the
    //    Next.js dev server proxies /ws/dashboard to the backend.
    const { protocol, host } = window.location
    const wsProtocol = protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${wsProtocol}//${host}/ws/dashboard`
    log.warn('URL source: same-origin fallback (NEXT_PUBLIC_WS_URL and NEXT_PUBLIC_API_URL are not set) →', url)
    return url
  }
  private _getRetryDelay(attempt: number): number {
    const d = Math.min(this.BASE_DELAY * Math.pow(2, attempt), this.MAX_DELAY)
    return Math.floor(d + Math.random() * 1000)
  }
  private _scheduleReconnect() {
    if (this._retry >= this.MAX_RETRIES) {
      log.error('Max retries reached — giving up. Check NEXT_PUBLIC_WS_URL / NEXT_PUBLIC_API_URL env vars.')
      this._state = ConnectionState.ERROR
      useDashboardStore.getState().setWsDiagnostics({
        reconnectAttempts: this._retry,
        lastError: 'Max reconnect attempts reached',
      })
      this._updateStoreState()
      return
    }
    this._state = ConnectionState.RECONNECTING
    this._retry++
    const delay = this._getRetryDelay(this._retry)
    log.info('Reconnecting in', delay, 'ms (attempt', this._retry, '/', this.MAX_RETRIES, ')')
    useDashboardStore.getState().setWsDiagnostics({ reconnectAttempts: this._retry })
    this._reconnectTimer = setTimeout(() => {
      // connect() bails out while state is RECONNECTING, so flip to
      // DISCONNECTED here or the timer can never reopen the socket.
      this._state = ConnectionState.DISCONNECTED
      this.connect()
    }, delay)
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
      log.info('Connected ✓', this._socket?.url)
      this._state = ConnectionState.CONNECTED
      this._retry = 0
      if (this._connTimeout) clearTimeout(this._connTimeout)
      this._connTimeout = null
      this._updateStoreState()
      useDashboardStore.getState().setWsDiagnostics({
        reconnectAttempts: this._retry,
        lastError: null,
      })
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
      const store = useDashboardStore.getState()

      if (msg.type === 'agent_status_update') {
        this._handleAgentStatusUpdate(msg, store)
        return
      }

      const messageTimestamp = msg.timestamp
        || (msg.payload as Record<string, unknown> | undefined)?.timestamp as string | undefined
        || new Date().toISOString()
      // Carry the event's subject (symbol / price / change) into the store so the
      // Live Activity feed can say *what* happened. Market frames put these at the
      // top level; other streams nest them under data/payload — check both.
      const detailSource = (msg.data ?? (msg as unknown as { payload?: unknown }).payload ?? null) as
        | Record<string, unknown>
        | null
      const rawSymbol = msg.symbol ?? (detailSource?.symbol as string | undefined)
      const rawPrice = msg.price ?? (detailSource?.price as string | number | undefined)
      const rawChange = (msg as unknown as { change?: unknown }).change ?? detailSource?.change
      const numPrice = rawPrice == null ? null : Number(rawPrice)
      const numChange = rawChange == null ? null : Number(rawChange)
      store.trackWsMessage({
        stream: msg.stream || msg.type || 'system',
        msgId: msg.msg_id || msg.message_id || null,
        timestamp: messageTimestamp,
        symbol: rawSymbol != null && rawSymbol !== '' ? String(rawSymbol) : null,
        price: numPrice != null && Number.isFinite(numPrice) ? numPrice : null,
        change: numChange != null && Number.isFinite(numChange) ? numChange : null,
        eventType: msg.type || null,
      })

      const eventPayload = msg.data ?? (msg as unknown as { payload?: unknown }).payload

      if (msg.type === 'dashboard_update' && msg.data) return this._handleDashboardUpdate(msg, store)
      if (msg.type === 'system_metric' && eventPayload) {
        const norm = this._normalizeSystemMetric(eventPayload)
        if (norm) store.addSystemMetric(norm)
        return
      }
      if (msg.stream === 'market_ticks') return this._handleMarketTick(msg, store)
      if (msg.type === 'PRICE_UPDATE' || msg.type === 'price_update') return this._handlePriceUpdate(msg, store)
      if (msg.stream === 'signals') {
        store.addSignal({ ...(msg as unknown as Record<string, unknown>), confidence: Number(msg.confidence) })
        return
      }
      if (msg.stream === 'orders') { store.updateOrder(msg as never); return }
      if (msg.type === 'trade_notification') return this._handleTradeNotification(msg, store)
      if (msg.stream === 'notifications') return this._handleNotification(msg, store)
      if (msg.stream === 'proposals') return this._handleProposal(msg, store)
      if (msg.stream === 'trade_lifecycle') return this._handleTradeFeed(msg, store)
      if (msg.stream === 'trade_completed') return this._handleClosedTrade(msg, store)
      if (msg.stream === 'agent_grades' || msg.stream === 'reflection_outputs') return this._handleLearningEvent(msg, store)
      if ((msg.type === 'agent_event' || msg.type === 'agent_status') && eventPayload) return this._handleAgentEvent(msg, store, eventPayload)
      if (msg.type === 'event' && eventPayload) return this._handleGenericEvent(msg, store, eventPayload)
      if (msg.stream === 'agent_logs') return this._handleAgentLog(msg, store)
    }
    this._socket.onclose = (event) => {
      const wasConnected = this._state === ConnectionState.CONNECTED
      log.warn('Closed — code:', event.code, 'reason:', event.reason || '(none)', 'wasConnected:', wasConnected)
      this._state = ConnectionState.DISCONNECTED
      this._cleanupSocket()
      this._updateStoreState()
      this.dispatch('ws-disconnected')
      // Reconnect with exponential backoff + jitter
      if (wasConnected) {
        this._scheduleReconnect()
      }
    }
    this._socket.onerror = (event) => {
      log.error('Socket error — state was:', this._state, event)
      useDashboardStore.getState().setWsDiagnostics({
        lastError: 'WebSocket error',
        reconnectAttempts: this._retry,
      })
      if (this._state === ConnectionState.CONNECTING) {
        this._state = ConnectionState.ERROR
        this._updateStoreState()
      }
    }
  }

  // --- Message Handlers ---
  private _handleAgentStatusUpdate(msg: WebSocketMessage, store: ReturnType<typeof useDashboardStore.getState>): void {
    if (Array.isArray((msg as unknown as Record<string, unknown>).agents)) {
      store.setAgentStatuses((msg as unknown as { agents: AgentHeartbeat[] }).agents)
    }
    const metricsRaw = (msg as unknown as Record<string, unknown>).metrics
    if (metricsRaw && typeof metricsRaw === 'object' && !Array.isArray(metricsRaw)) {
      store.setPipelineMetrics(metricsRaw as Record<string, number>)
    }
  }

  private _handleDashboardUpdate(msg: WebSocketMessage, store: ReturnType<typeof useDashboardStore.getState>): void {
    try {
      store.hydrateDashboard(this._normalizeDashboardData(msg.data))
    } catch (error) {
      log.error('Error hydrating dashboard:', error)
    }
  }

  private _handleMarketTick(msg: WebSocketMessage, store: ReturnType<typeof useDashboardStore.getState>): void {
    const price = Number(msg.price)
    const symbol = msg.symbol || 'UNKNOWN'
    const previousPrice = store.prices[symbol]?.price ?? price
    const change = Number.isFinite(price) ? price - previousPrice : 0
    if (Number.isFinite(price)) store.updatePrice(symbol, price, change)
    store.trackMarketTick(symbol)
  }

  private _handlePriceUpdate(msg: WebSocketMessage, store: ReturnType<typeof useDashboardStore.getState>): void {
    const price = Number(msg.price)
    const symbol = msg.symbol
    if (!symbol) return
    const currentPriceData = store.prices[symbol]
    const msgTimestamp = msg.timestamp || new Date().toISOString()
    const msgTs = Date.parse(msgTimestamp)
    const storedTs = currentPriceData?.updatedAt ? Date.parse(currentPriceData.updatedAt) : -Infinity
    const shouldUpdate = !currentPriceData?.updatedAt || (Number.isFinite(msgTs) && msgTs > storedTs)
    if (shouldUpdate && Number.isFinite(price)) {
      const previousPrice = currentPriceData?.price ?? price
      store.updatePrice(symbol, price, price - previousPrice)
      store.trackMarketTick(symbol)
    }
  }

  private _handleTradeNotification(msg: WebSocketMessage, store: ReturnType<typeof useDashboardStore.getState>): void {
    const raw = msg as unknown as Record<string, unknown>
    const side = String(raw.side || 'buy')
    const fillPrice = Number(raw.fill_price ?? 0)
    const pnlRaw = raw.pnl
    // Preserve null pnl for opens (BUY): equity curve skips null-pnl orders.
    const pnl = (pnlRaw != null && pnlRaw !== '') ? Number(pnlRaw) : (null as unknown as number)
    const ts = String(raw.filled_at || msg.timestamp || new Date().toISOString())
    store.updateOrder({
      order_id: raw.order_id as string,
      symbol: String(raw.symbol || ''),
      side: (side === 'sell' ? 'short' : 'long') as 'long' | 'short',
      quantity: Number(raw.qty ?? 0),
      entry_price: fillPrice,
      current_price: fillPrice,
      pnl,
      timestamp: ts,
      filled_at: ts,
      status: 'filled',
      trace_id: raw.trace_id as string,
      source: raw.source as string,
    } as import('@/stores/useDashboardStore').Order)
  }

  private _handleNotification(msg: WebSocketMessage, store: ReturnType<typeof useDashboardStore.getState>): void {
    const messageRaw = msg as unknown as Record<string, unknown>
    const payloadRaw = this._coerceObject(messageRaw.payload)
    const raw = msg.type === 'event' && payloadRaw
      ? { ...payloadRaw, timestamp: payloadRaw.timestamp ?? msg.timestamp, stream_source: payloadRaw.stream_source ?? msg.stream }
      : { ...messageRaw, stream_source: messageRaw.stream_source ?? messageRaw.source ?? msg.stream }
    store.addNotification(raw)
  }

  private _handleProposal(msg: WebSocketMessage, store: ReturnType<typeof useDashboardStore.getState>): void {
    const raw = msg as unknown as Record<string, unknown>
    // Preserve the backend id (trace_id / msg_id) so this proposal dedups
    // against the REST-polled copy and the approve/reject PATCH can match it.
    const stableId = raw.id ?? raw.trace_id ?? raw.msg_id
    store.addProposal({
      id: stableId != null ? String(stableId) : undefined,
      proposal_type: (raw.proposal_type || 'parameter_change') as import('@/stores/useDashboardStore').ProposalType,
      // `content` may be a structured object (challenger promotions carry
      // { strategy, shadow_edge, reason }) — coerce so it never renders as
      // "[object Object]" in the proposal queue.
      content: coerceProposalContent(raw.content || raw.description),
      strategy_name:
        (raw.strategy_name as string | undefined) ?? proposalStrategyName(raw.content),
      requires_approval: raw.requires_approval !== false,
      reflection_trace_id: raw.reflection_trace_id as string | undefined,
      trace_id: (raw.trace_id as string | undefined) ?? undefined,
      confidence: typeof raw.confidence === 'number' ? raw.confidence : undefined,
      status: (raw.status as import('@/stores/useDashboardStore').ProposalStatus) ?? 'pending',
      timestamp: msg.timestamp || new Date().toISOString(),
    })
  }

  private _handleTradeFeed(msg: WebSocketMessage, store: ReturnType<typeof useDashboardStore.getState>): void {
    const raw = { ...(msg as unknown as Record<string, unknown>), created_at: msg.timestamp }
    store.addTradeFeedItem(normalizeTradeFeedItem(raw))
  }

  private _handleClosedTrade(msg: WebSocketMessage, store: ReturnType<typeof useDashboardStore.getState>): void {
    // Every `trade_completed` stream event is one round-trip close. Without
    // this the Closed Trades panel only refreshed from connect snapshots, so
    // closes that happened while the WS was connected never appeared.
    store.addClosedTrade(normalizeClosedTrade(msg as unknown as Record<string, unknown>))
  }

  private _handleLearningEvent(msg: WebSocketMessage, store: ReturnType<typeof useDashboardStore.getState>): void {
    store.addLearningEvent({
      type: msg.stream === 'agent_grades' ? 'trade_evaluated' : 'reflection',
      timestamp: msg.timestamp || new Date().toISOString(),
      ...(msg as unknown as Record<string, unknown>),
    })
  }

  private _handleAgentEvent(msg: WebSocketMessage, store: ReturnType<typeof useDashboardStore.getState>, payload: unknown): void {
    const normalizedPayload = msg.type === 'agent_status'
      ? {
          agent_name: (payload as Record<string, unknown>).name,
          timestamp: (payload as Record<string, unknown>).updated_at || new Date().toISOString(),
          message: (payload as Record<string, unknown>).last_task || 'status_update',
          ...(payload as Record<string, unknown>),
        }
      : payload
    const norm = this._normalizeAgentEvent(normalizedPayload)
    if (norm) store.addAgentLog(norm)
  }

  private _handleGenericEvent(msg: WebSocketMessage, store: ReturnType<typeof useDashboardStore.getState>, payload: unknown): void {
    const unwrapped = ((payload as Record<string, unknown>).payload as Record<string, unknown> | undefined) ?? (payload as Record<string, unknown>)
    const coerced = this._coerceObject(unwrapped)
    if (!coerced) return
    const enriched: Record<string, unknown> = {
      ...coerced,
      stream: msg.stream || coerced.stream,
      event_type: msg.event_type || coerced.event_type || coerced.type,
      timestamp: msg.timestamp || coerced.timestamp,
    }
    const looksLikeAgentEvent = Boolean(
      enriched['agent_name'] || enriched['agent'] ||
      enriched['stream'] === 'agent_logs' || enriched['event_type'] === 'agent_log'
    )
    if (looksLikeAgentEvent) {
      const norm = this._normalizeAgentEvent(enriched)
      if (norm) store.addAgentLog(norm)
    }
  }

  private _handleAgentLog(msg: WebSocketMessage, store: ReturnType<typeof useDashboardStore.getState>): void {
    const source = msg as unknown as Record<string, unknown>
    const payloadObj = (source.payload as Record<string, unknown> | undefined) ?? {}
    const norm = this._normalizeAgentEvent({
      ...source,
      ...payloadObj,
      agent_name: source.agent || source.source || payloadObj.agent || source['agent_name'],
      timestamp: msg.timestamp || payloadObj.timestamp || new Date().toISOString(),
    })
    if (norm) store.addAgentLog(norm)
  }

  // --- Normalization ---
  /**
   * Shape a dashboard_update payload for the store: `orders` and the other
   * collection fields may arrive as arrays, keyed objects, or be missing —
   * normalize all of them to arrays so hydrateDashboard never branches.
   */
  private _normalizeDashboardData(data: unknown): DashboardData {
    // This function IS the wire-shape coercion — every collection field is
    // forced to an array below, which is exactly the DashboardData contract.
    if (!data || typeof data !== 'object' || Array.isArray(data)) return data as DashboardData

    const normalized: Record<string, unknown> = { ...(data as Record<string, unknown>) }

    const isRecord = (v: unknown): v is Record<string, unknown> =>
      typeof v === 'object' && v != null && !Array.isArray(v)

    const orders = normalized.orders
    if (isRecord(orders)) {
      // Prefer the known order-array keys; fall back to the object's values
      // (excluding metadata entries, which carry a top-level timestamp).
      const ordersArray: unknown[] = []
      const orderKeys = ['orders_last_hour', 'recent_orders', 'active_orders', 'pending_orders']
      for (const key of orderKeys) {
        const orderArray = orders[key]
        if (Array.isArray(orderArray)) ordersArray.push(...orderArray)
      }
      if (ordersArray.length === 0) {
        ordersArray.push(...Object.values(orders).filter((item) => isRecord(item) && !item.timestamp))
      }
      normalized.orders = ordersArray
    } else if (!orders) {
      normalized.orders = []
    }

    const arrayFields = ['agent_logs', 'system_metrics', 'signals', 'positions', 'risk_alerts', 'learning_events', 'notifications']
    for (const field of arrayFields) {
      const value = normalized[field]
      if (value && !Array.isArray(value)) {
        normalized[field] = isRecord(value) ? Object.values(value).filter(isRecord) : []
      } else if (!value) {
        normalized[field] = []
      }
    }

    return normalized as DashboardData
  }

  private _normalizeAgentEvent(value: unknown): AgentLog | null {
    if (!value || typeof value !== 'object') return null
    const raw = value as Record<string, unknown>
    const inferredAgentName =
      raw.agent_name || raw.agent || raw.source_agent || (raw.stream === 'agent_logs' ? 'Agent Pipeline' : null)
    if (!inferredAgentName) return null
    return {
      agent_name: String(inferredAgentName),
      event_type: this._normalizeEventType(String(raw.event_type || raw.action || raw.type || 'processed')),
      timestamp: String(raw.timestamp || raw.created_at || new Date().toISOString()),
      symbol: raw.symbol as string | undefined,
      action: raw.action as string | undefined,
      latency_ms: Number(raw.latency_ms) || 0,
      primary_edge: raw.primary_edge as string | undefined,
      ...(raw.stream ? { stream: raw.stream } : null),
      ...(raw.message_id ? { message_id: raw.message_id } : null),
      ...(raw.data ? { data: raw.data } : null),
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
  private _normalizeSystemMetric(value: unknown): SystemMetric | null {
    if (!value || typeof value !== 'object') return null
    const raw = value as Record<string, unknown>
    return {
      metric_name: String(raw.metric_name || raw.name || 'unknown'),
      value: Number(raw.value) || 0,
      timestamp: String(raw.timestamp || raw.created_at || new Date().toISOString()),
      labels: (raw.labels as Record<string, string> | undefined) ?? {},
      ...(raw.unit ? { unit: raw.unit } : null),
      ...(raw.tags ? { tags: raw.tags } : null),
    } as SystemMetric
  }
  private _normalizeEventType(val: string): string {
    if (!val || typeof val !== 'string') return 'unknown'
    const map: Record<string, string> = {
      buy: 'signal', sell: 'signal', purchase: 'signal', trade: 'signal', order: 'signal',
      execution: 'order', execute: 'order', fill: 'order',
      market_tick: 'tick', price_update: 'tick', PRICE_UPDATE: 'tick', quote: 'tick',
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
  const setWsConnected = useDashboardStore((state) => state.setWsConnected)
  const wsConnected = useDashboardStore((state) => state.wsConnected)
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
