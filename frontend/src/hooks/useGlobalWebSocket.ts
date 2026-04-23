"use client";
import { useEffect, useRef } from "react";
import { useCodexStore, type AgentStatus } from "@/stores/useCodexStore";

// --- Types ---
type WebSocketMessage = {
  type: string;
  schema_version?: string;
  timestamp?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload?: any;
  stream?: string;
  event_type?: string;
  message_id?: string;
  msg_id?: string;
  symbol?: string;
  price?: string | number;
  side?: string;
  confidence?: string | number;
};

type WebSocketData = any;

export enum ConnectionState {
  DISCONNECTED = "disconnected",
  CONNECTING = "connecting",
  CONNECTED = "connected",
  RECONNECTING = "reconnecting",
  ERROR = "error",
}

type Listener = (event: CustomEvent) => void;

// --- WebSocketManager Singleton ---
class WebSocketManager {
  private static _instance: WebSocketManager | null = null;
  private _socket: WebSocket | null = null;
  private _state: ConnectionState = ConnectionState.DISCONNECTED;
  private _retry: number = 0;
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _connTimeout: ReturnType<typeof setTimeout> | null = null;
  private readonly MAX_RETRIES = 8;
  private readonly BASE_DELAY = 2000;
  private readonly MAX_DELAY = 30000;
  private readonly CONN_TIMEOUT = 10000;
  private readonly RETRY_RESET_DELAY = 60000;
  private _lastConnectAt: number = 0;

  // Event listeners: eventName -> Set<Listener>
  private _listeners: Map<string, Set<Listener>> = new Map();
  private _storeUpdate: (() => void) | null = null;

  private constructor() {}
  static get instance() {
    if (!this._instance) this._instance = new WebSocketManager();
    return this._instance;
  }

  // --- Event Listener System ---
  addEventListener(event: string, listener: Listener) {
    if (!this._listeners.has(event)) this._listeners.set(event, new Set());
    const set = this._listeners.get(event)!;
    set.add(listener);
    window.addEventListener(event, listener as EventListener);
  }
  removeEventListener(event: string, listener: Listener) {
    const set = this._listeners.get(event);
    if (set) {
      set.delete(listener);
      window.removeEventListener(event, listener as EventListener);
      if (set.size === 0) this._listeners.delete(event);
    }
  }
  removeAllEventListeners() {
    for (const [event, set] of Array.from(this._listeners.entries())) {
      for (const l of Array.from(set))
        window.removeEventListener(event, l as EventListener);
    }
    this._listeners.clear();
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  dispatch(event: string, detail?: any) {
    try {
      window.dispatchEvent(new CustomEvent(event, { detail }));
    } catch {}
  }

  // --- Public API ---
  get state() {
    return this._state;
  }
  get socket() {
    return this._socket;
  }
  isConnected() {
    return (
      this._state === ConnectionState.CONNECTED &&
      this._socket?.readyState === WebSocket.OPEN
    );
  }
  connect() {
    if (typeof window === "undefined") return;
    if (
      this._state === ConnectionState.CONNECTING ||
      this._state === ConnectionState.CONNECTED ||
      this._state === ConnectionState.RECONNECTING
    ) {
      console.info("[WS] connect() skipped — already in state:", this._state);
      return;
    }
    this._cleanupSocket();
    this._state = ConnectionState.CONNECTING;
    this._updateStoreState();
    const url = this._getWsUrl();
    if (!url) {
      console.error("[WS] No URL resolved — cannot connect");
      this._state = ConnectionState.ERROR;
      this._updateStoreState();
      return;
    }
    console.info("[WS] Connecting to", url, "(attempt", this._retry + 1, ")");
    try {
      this._socket = new WebSocket(url);
      this._lastConnectAt = Date.now();
      this._setupSocketHandlers();
      this._connTimeout = setTimeout(() => {
        if (this._state === ConnectionState.CONNECTING) {
          console.error(
            "[WS] Connection timed out after",
            this.CONN_TIMEOUT,
            "ms →",
            url,
          );
          this._state = ConnectionState.ERROR;
          this._cleanupSocket();
          this._updateStoreState();
        }
      }, this.CONN_TIMEOUT);
    } catch (err) {
      console.error("[WS] Failed to create WebSocket:", err);
      this._state = ConnectionState.ERROR;
      this._updateStoreState();
    }
  }
  disconnect() {
    this._cleanupSocket();
    this.removeAllEventListeners();
    this._state = ConnectionState.DISCONNECTED;
    this._retry = 0;
    this._updateStoreState();
  }
  reconnect() {
    this._retry = 0;
    this.connect();
  }
  setStoreUpdate(fn: (() => void) | null) {
    this._storeUpdate = fn;
  }

  // --- Private methods ---
  private _getWsUrl(): string {
    if (typeof window === "undefined") return "";

    // 1. Explicit WS URL env var — always wins.
    const envUrl = process.env.NEXT_PUBLIC_WS_URL;
    if (envUrl) {
      const wsBase = envUrl
        .replace(/^https:\/\//, "wss://")
        .replace(/^http:\/\//, "ws://")
        .replace(/\/$/, "");
      const url = `${wsBase}/ws/dashboard`;
      console.info("[WS] URL source: NEXT_PUBLIC_WS_URL →", url);
      return url;
    }

    // 2. Derive from the API base URL — handles the common case where only
    //    NEXT_PUBLIC_API_URL is set. Strip any trailing /api path segment so
    //    we end up at the service root (where /ws/dashboard lives).
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    if (apiUrl && /^https?:\/\//.test(apiUrl)) {
      const wsBase = apiUrl
        .replace(/\/api\/?$/, "") // strip trailing /api
        .replace(/^https:\/\//, "wss://")
        .replace(/^http:\/\//, "ws://")
        .replace(/\/$/, "");
      const url = `${wsBase}/ws/dashboard`;
      console.info("[WS] URL source: NEXT_PUBLIC_API_URL (derived) →", url);
      return url;
    }

    // 3. Same-origin fallback — only correct in local development where the
    //    Next.js dev server proxies /ws/dashboard to the backend.
    const { protocol, host } = window.location;
    const wsProtocol = protocol === "https:" ? "wss:" : "ws:";
    const url = `${wsProtocol}//${host}/ws/dashboard`;
    console.warn(
      "[WS] URL source: same-origin fallback (NEXT_PUBLIC_WS_URL and NEXT_PUBLIC_API_URL are not set) →",
      url,
    );
    return url;
  }
  private _getRetryDelay(attempt: number): number {
    const d = Math.min(this.BASE_DELAY * Math.pow(2, attempt), this.MAX_DELAY);
    return Math.floor(d + Math.random() * 1000);
  }
  private _cleanupSocket() {
    if (this._socket) {
      this._socket.onopen = null;
      this._socket.onmessage = null;
      this._socket.onerror = null;
      this._socket.onclose = null;
      if (
        this._socket.readyState === WebSocket.OPEN ||
        this._socket.readyState === WebSocket.CONNECTING
      ) {
        try {
          this._socket.close(1000, "Cleanup");
        } catch {}
      }
    }
    this._socket = null;
    if (this._reconnectTimer) clearTimeout(this._reconnectTimer);
    this._reconnectTimer = null;
    if (this._connTimeout) clearTimeout(this._connTimeout);
    this._connTimeout = null;
  }
  private _updateStoreState() {
    if (this._storeUpdate) {
      try {
        this._storeUpdate();
      } catch {}
    }
  }
  private _setupSocketHandlers() {
    if (!this._socket) return;
    this._socket.onopen = () => {
      console.info("[WS] Connected ✓", this._socket?.url);
      this._state = ConnectionState.CONNECTED;
      this._retry = 0;
      if (this._connTimeout) clearTimeout(this._connTimeout);
      this._connTimeout = null;
      this._updateStoreState();
      this.dispatch("ws-connected");
      setTimeout(() => {
        if (this._state === ConnectionState.CONNECTED) this._retry = 0;
      }, this.RETRY_RESET_DELAY);
    };
    this._socket.onmessage = (event) => {
      let msg: any | null = null;
      try {
        msg = JSON.parse(event.data);
      } catch {}
      if (!msg) return;
      this.dispatch("ws-message", msg);
      // Store logic with safe data normalization
      const store = useCodexStore.getState();

      // Agent status push — replaces client-side HTTP polling
      if (msg.type === "agent_status_update") {
        if (Array.isArray((msg as unknown as Record<string, unknown>).agents)) {
          store.setAgentStatuses(
            (msg as unknown as { agents: AgentStatus[] }).agents,
          );
        }
        const metricsRaw = (msg as unknown as Record<string, unknown>).metrics;
        if (
          metricsRaw &&
          typeof metricsRaw === "object" &&
          !Array.isArray(metricsRaw)
        ) {
          store.setPipelineMetrics(metricsRaw as Record<string, number>);
        }
        return;
      }

      const messageTimestamp =
        msg.timestamp ||
        ((msg.payload as Record<string, unknown> | undefined)?.timestamp as
          | string
          | undefined) ||
        new Date().toISOString();
      store.trackWsMessage({
        stream: msg.stream || msg.type || "system",
        msgId: msg.msg_id || msg.message_id || null,
        timestamp: messageTimestamp,
      });
      const eventPayload =
        msg.data ?? (msg as unknown as { payload?: unknown }).payload;
      if (msg.type === "dashboard_update" && msg.data) {
        try {
          // Normalize data safely before passing to store
          const normalizedData = this._normalizeDashboardData(msg.data);
          store.hydrateDashboard(normalizedData);
        } catch (error) {
          console.error("Error hydrating dashboard:", error);
        }
        if (Array.isArray(msg.data.agent_logs)) {
          for (const log of msg.data.agent_logs) {
            const norm = this._normalizeAgentEvent(log);
            if (norm) store.addAgentLog(norm);
          }
        }
        if (Array.isArray(msg.data.system_metrics)) {
          for (const metric of msg.data.system_metrics) {
            const norm = this._normalizeSystemMetric(metric);
            if (norm) store.addSystemMetric(norm);
          }
        }
      } else if (msg.type === "system_metric" && eventPayload) {
        const norm = this._normalizeSystemMetric(eventPayload);
        if (norm) store.addSystemMetric(norm);
      } else if (msg.stream === "market_ticks") {
        const price = Number(msg.price);
        const symbol = msg.symbol || "UNKNOWN";
        const previousPrice = store.prices[symbol]?.price ?? price;
        const change = Number.isFinite(price) ? price - previousPrice : 0;
        if (Number.isFinite(price)) store.updatePrice(symbol, price, change);
        store.trackMarketTick(symbol);
      } else if (msg.type === "price_update" && msg.symbol && msg.price) {
        // Handle price updates from background worker
        const price = Number(msg.price);
        const symbol = msg.symbol;
        const currentPriceData = store.prices[symbol];
        const messageTimestamp = msg.timestamp || new Date().toISOString();

        // Only update if WebSocket data is newer than existing data
        const shouldUpdate =
          !currentPriceData?.updatedAt ||
          new Date(messageTimestamp) > new Date(currentPriceData.updatedAt);

        if (shouldUpdate && Number.isFinite(price)) {
          const previousPrice = currentPriceData?.price ?? price;
          const change = price - previousPrice;
          store.updatePrice(symbol, price, change);
          store.trackMarketTick(symbol);
        }
      } else if (msg.stream === "signals") {
        store.addSignal({
          ...(msg as unknown as Record<string, unknown>),
          confidence: Number(msg.confidence),
        });
      } else if (msg.stream === "orders") {
        // Stream payloads are partially typed; store merge handles sparse updates.
        store.updateOrder(msg as never);
      } else if (msg.stream === "notifications") {
        const raw = msg as unknown as Record<string, unknown>;
        store.addNotification({
          severity: ((raw.severity as string) ||
            "INFO") as import("@/stores/useCodexStore").NotificationSeverity,
          message: String(raw.message || raw.summary || ""),
          notification_type: String(
            raw.notification_type || raw.type || "system",
          ),
          stream_source: String(raw.stream_source || raw.source || ""),
          trace_id: typeof raw.trace_id === "string" ? raw.trace_id : undefined,
          state:
            String(raw.state || "open").toLowerCase() === "resolved"
              ? "resolved"
              : "open",
          timestamp: msg.timestamp || new Date().toISOString(),
        });
      } else if (msg.stream === "proposals") {
        const raw = msg as unknown as Record<string, unknown>;
        store.addProposal({
          proposal_type: (raw.proposal_type ||
            "parameter_change") as import("@/stores/useCodexStore").ProposalType,
          content: String(raw.content || raw.description || ""),
          requires_approval: raw.requires_approval !== false,
          reflection_trace_id: raw.reflection_trace_id as string | undefined,
          confidence:
            typeof raw.confidence === "number" ? raw.confidence : undefined,
          timestamp: msg.timestamp || new Date().toISOString(),
        });
      } else if (msg.stream === "trade_lifecycle") {
        // Live trade fill / grade update pushed from execution_engine / grade_agent
        const raw = msg as unknown as Record<string, unknown>;
        store.addTradeFeedItem({
          id: (raw.id as string | null) ?? String(Date.now()),
          symbol: String(raw.symbol ?? ""),
          side: (raw.side as "buy" | "sell") ?? "buy",
          qty: typeof raw.qty === "number" ? raw.qty : null,
          entry_price:
            typeof raw.entry_price === "number" ? raw.entry_price : null,
          exit_price:
            typeof raw.exit_price === "number" ? raw.exit_price : null,
          pnl: typeof raw.pnl === "number" ? raw.pnl : null,
          pnl_percent:
            typeof raw.pnl_percent === "number" ? raw.pnl_percent : null,
          order_id: (raw.order_id as string | null) ?? null,
          execution_trace_id: (raw.execution_trace_id as string | null) ?? null,
          signal_trace_id: (raw.signal_trace_id as string | null) ?? null,
          grade: (raw.grade as string | null) ?? null,
          grade_score:
            typeof raw.grade_score === "number" ? raw.grade_score : null,
          grade_label: (raw.grade_label as string | null) ?? null,
          status: String(raw.status ?? "filled"),
          filled_at: (raw.filled_at as string | null) ?? null,
          graded_at: (raw.graded_at as string | null) ?? null,
          reflected_at: (raw.reflected_at as string | null) ?? null,
          created_at: msg.timestamp ?? new Date().toISOString(),
        });
      } else if (
        msg.stream === "agent_grades" ||
        msg.stream === "reflection_outputs"
      ) {
        store.addLearningEvent({
          type:
            msg.stream === "agent_grades" ? "trade_evaluated" : "reflection",
          timestamp: msg.timestamp || new Date().toISOString(),
          ...(msg as unknown as Record<string, unknown>),
        });
      } else if (
        (msg.type === "agent_event" || msg.type === "agent_status") &&
        eventPayload
      ) {
        const normalizedAgentPayload =
          msg.type === "agent_status"
            ? {
                agent_name: (eventPayload as Record<string, unknown>).name,
                timestamp:
                  (eventPayload as Record<string, unknown>).updated_at ||
                  new Date().toISOString(),
                message:
                  (eventPayload as Record<string, unknown>).last_task ||
                  "status_update",
                ...(eventPayload as Record<string, unknown>),
              }
            : eventPayload;
        const norm = this._normalizeAgentEvent(normalizedAgentPayload);
        if (norm) store.addAgentLog(norm);
      } else if (msg.type === "event" && eventPayload) {
        const unwrappedPayload =
          ((eventPayload as Record<string, unknown>).payload as
            | Record<string, unknown>
            | undefined) ?? (eventPayload as Record<string, unknown>);
        const normalizedEventPayload = this._coerceObject(unwrappedPayload);
        if (!normalizedEventPayload) return;

        const payloadWithContext: Record<string, unknown> = {
          ...normalizedEventPayload,
          stream: msg.stream || normalizedEventPayload.stream,
          event_type:
            msg.event_type ||
            normalizedEventPayload.event_type ||
            normalizedEventPayload.type,
          timestamp: msg.timestamp || normalizedEventPayload.timestamp,
        };

        const looksLikeAgentEvent = Boolean(
          payloadWithContext["agent_name"] ||
          payloadWithContext["agent"] ||
          payloadWithContext["stream"] === "agent_logs" ||
          payloadWithContext["event_type"] === "agent_log",
        );

        if (looksLikeAgentEvent) {
          const norm = this._normalizeAgentEvent(payloadWithContext);
          if (norm) store.addAgentLog(norm);
        }
      } else if (msg.stream === "agent_logs") {
        const source = msg as unknown as Record<string, unknown>;
        const payloadObj =
          (source.payload as Record<string, unknown> | undefined) ?? {};
        const norm = this._normalizeAgentEvent({
          ...source,
          ...payloadObj,
          agent_name:
            source.agent ||
            source.source ||
            payloadObj.agent ||
            source["agent_name"],
          timestamp:
            msg.timestamp || payloadObj.timestamp || new Date().toISOString(),
        });
        if (norm) store.addAgentLog(norm);
      }
    };
    this._socket.onclose = (event) => {
      const wasConnected = this._state === ConnectionState.CONNECTED;
      console.warn(
        "[WS] Closed — code:",
        event.code,
        "reason:",
        event.reason || "(none)",
        "wasConnected:",
        wasConnected,
      );
      this._state = ConnectionState.DISCONNECTED;
      this._cleanupSocket();
      this._updateStoreState();
      this.dispatch("ws-disconnected");
      // Reconnect with exponential backoff + jitter
      if (wasConnected && this._retry < this.MAX_RETRIES) {
        this._state = ConnectionState.RECONNECTING;
        this._retry++;
        const delay = this._getRetryDelay(this._retry);
        console.info(
          "[WS] Reconnecting in",
          delay,
          "ms (attempt",
          this._retry,
          "/",
          this.MAX_RETRIES,
          ")",
        );
        this._reconnectTimer = setTimeout(() => this.connect(), delay);
      } else if (this._retry >= this.MAX_RETRIES) {
        console.error(
          "[WS] Max retries reached — giving up. Check NEXT_PUBLIC_WS_URL / NEXT_PUBLIC_API_URL env vars.",
        );
        this._state = ConnectionState.ERROR;
        this._updateStoreState();
      }
    };
    this._socket.onerror = (event) => {
      console.error("[WS] Socket error — state was:", this._state, event);
      if (this._state === ConnectionState.CONNECTING) {
        this._state = ConnectionState.ERROR;
        this._updateStoreState();
      }
    };
  }

  // --- Normalization ---
  private _normalizeDashboardData(data: any): any {
    if (!data || typeof data !== "object") return data;

    const normalized = { ...data };

    // Normalize orders - handle both object and array formats
    if (
      normalized.orders &&
      typeof normalized.orders === "object" &&
      !Array.isArray(normalized.orders)
    ) {
      // Convert orders object to array format expected by store
      // Extract actual order arrays from the object
      const ordersArray: WebSocketData[] = [];

      // Look for common order array keys
      const orderKeys = [
        "orders_last_hour",
        "recent_orders",
        "active_orders",
        "pending_orders",
      ];
      for (const key of orderKeys) {
        const orderArray = normalized.orders[key];
        if (Array.isArray(orderArray)) {
          ordersArray.push(...orderArray);
        }
      }

      // If no arrays found, convert object values to array
      if (ordersArray.length === 0) {
        const objectValues = Object.values(normalized.orders) as unknown[];
        ordersArray.push(
          ...objectValues.filter(
            (item: unknown) =>
              typeof item === "object" &&
              item !== null &&
              !(item as Record<string, unknown>).timestamp, // exclude metadata
          ),
        );
      }

      normalized.orders = ordersArray;
    } else if (!normalized.orders) {
      normalized.orders = [];
    }

    // Normalize other array fields safely
    const arrayFields = [
      "agent_logs",
      "system_metrics",
      "signals",
      "positions",
      "risk_alerts",
      "learning_events",
    ];
    for (const field of arrayFields) {
      if (normalized[field] && !Array.isArray(normalized[field])) {
        if (typeof normalized[field] === "object") {
          // Convert object to array of values
          const objectValues = Object.values(normalized[field]) as Record<string, unknown>[];
          normalized[field] = objectValues.filter(
            (item: Record<string, unknown>) => typeof item === "object" && item !== null,
          );
        } else {
          // Set to empty array if not convertible
          normalized[field] = [];
        }
      } else if (!normalized[field]) {
        normalized[field] = [];
      }
    }

    return normalized;
  }

  private _normalizeAgentEvent(raw: WebSocketData): WebSocketData | null {
    if (!raw || typeof raw !== "object") return null;
    const inferredAgentName =
      raw.agent_name ||
      raw.agent ||
      raw.source_agent ||
      (raw.stream === "agent_logs" ? "Agent Pipeline" : "Unknown");
    return {
      agent_name: inferredAgentName,
      event_type: this._normalizeEventType(
        raw.event_type || raw.action || raw.type || "processed",
      ),
      timestamp: raw.timestamp || raw.created_at || new Date().toISOString(),
      symbol: raw.symbol,
      action: raw.action,
      latency_ms: Number(raw.latency_ms) || 0,
      primary_edge: raw.primary_edge,
      ...(raw.stream && { stream: raw.stream }),
      ...(raw.message_id && { message_id: raw.message_id }),
      ...(raw.data && { data: raw.data }),
      ...raw,
    };
  }

  private _coerceObject(value: unknown): Record<string, unknown> | null {
    if (!value) return null;
    if (typeof value === "object" && !Array.isArray(value)) {
      return value as Record<string, unknown>;
    }
    if (typeof value === "string") {
      try {
        const parsed = JSON.parse(value);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          return parsed as Record<string, unknown>;
        }
      } catch {
        return null;
      }
    }
    return null;
  }

  private _normalizeSystemMetric(raw: WebSocketData): WebSocketData | null {
    if (!raw || typeof raw !== "object") return null;
    return {
      metric_name: raw.metric_name || raw.name || "unknown",
      value: Number(raw.value) || 0,
      timestamp: raw.timestamp || raw.created_at || new Date().toISOString(),
      labels: raw.labels || {},
      ...(raw.unit && { unit: raw.unit }),
      ...(raw.tags && { tags: raw.tags }),
      ...raw,
    };
  }

  private _normalizeEventType(val: string): string {
    const map = {
      buy: "signal",
      sell: "signal",
      purchase: "signal",
      trade: "signal",
      order: "signal",
      execution: "order",
      execute: "order",
      fill: "order",
      market_tick: "tick",
      price_update: "tick",
      quote: "tick",
      analysis: "analysis",
      reasoning: "analysis",
      grading: "grade",
      assessment: "grade",
      learning: "learning",
      training: "learning",
      reflection: "reflection",
      review: "reflection",
      notification: "notification",
      alert: "notification",
      message: "notification",
    };
    return map[val.toLowerCase()] || val.toLowerCase();
  }
}

// --- Hook ---
export function useGlobalWebSocket() {
  const setWsConnected = useCodexStore((state) => state.setWsConnected);
  const wsConnected = useCodexStore((state) => state.wsConnected);
  const manager = WebSocketManager.instance;
  const initialized = useRef(false);

  // Provide store update fn to manager for reactive state
  useEffect(() => {
    manager.setStoreUpdate(() => setWsConnected(manager.isConnected()));
    return () => {
      manager.setStoreUpdate(null);
    };
    // eslint-disable-next-line
  }, [setWsConnected]);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    if (typeof window === "undefined") return;
    // Connect if not connected
    if (!manager.isConnected()) manager.connect();
    // Event listeners for UI reactivity (store is primary, but also for redundancy)
    const onConnect = () => setWsConnected(true);
    const onDisconnect = () => setWsConnected(false);
    manager.addEventListener("ws-connected", onConnect);
    manager.addEventListener("ws-disconnected", onDisconnect);
    return () => {
      manager.removeEventListener("ws-connected", onConnect);
      manager.removeEventListener("ws-disconnected", onDisconnect);
    };
    // eslint-disable-next-line
  }, [setWsConnected]);

  useEffect(() => {
    return () => {
      manager.removeAllEventListeners();
    };
  }, [manager]);

  return {
    socket: manager.socket,
    isConnected: wsConnected,
    connectionState: manager.state,
    reconnect: () => manager.reconnect(),
    disconnect: () => manager.disconnect(),
  };
}
