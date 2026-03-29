// WebSocket event types for type safety

export interface WebSocketMessage {
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

export interface DashboardUpdateData {
  agent_logs?: Array<{
    agent_name?: string
    agent?: string
    source_agent?: string
    action?: string
    type?: string
    timestamp?: string
    created_at?: string
    symbol?: string
    latency_ms?: number
    primary_edge?: string
    stream?: string
    message_id?: string
    data?: unknown
  }>
  system_metrics?: Array<{
    metric_name?: string
    name?: string
    value?: number
    timestamp?: string
    created_at?: string
    labels?: Record<string, unknown>
    unit?: string
    tags?: unknown
  }>
  [key: string]: unknown
}

export interface SystemMetricData {
  metric_name?: string
  name?: string
  value?: number
  timestamp?: string
  created_at?: string
  labels?: Record<string, unknown>
  unit?: string
  tags?: unknown
}

export interface PriceUpdateData {
  symbol?: string
  price?: string | number
  timestamp?: string
}

export interface SignalData {
  [key: string]: unknown
  confidence?: number
}

export interface OrderData {
  [key: string]: unknown
}

export interface NotificationData {
  [key: string]: unknown
}

export interface AgentEventData {
  name?: string
  agent_name?: string
  action?: string
  type?: string
  timestamp?: string
  updated_at?: string
  created_at?: string
  symbol?: string
  latency_ms?: number
  primary_edge?: string
  stream?: string
  message_id?: string
  data?: unknown
}

export interface SystemEventData {
  type?: string
  data?: unknown
  [key: string]: unknown
}

export interface AgentLogsData {
  agent?: string
  source?: string
  source_agent?: string
  action?: string
  type?: string
  timestamp?: string
  created_at?: string
  symbol?: string
  latency_ms?: number
  primary_edge?: string
  stream?: string
  message_id?: string
  data?: unknown
  payload?: {
    agent?: string
    [key: string]: unknown
  }
  agent_name?: string
}

export interface CustomEventDetail<T = unknown> {
  data?: T
  symbol?: string
  price?: number
  timestamp?: string
  [key: string]: unknown
}

export type CustomEventType = CustomEvent & {
  detail: CustomEventDetail
}
