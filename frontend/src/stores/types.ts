/**
 * Dashboard store domain types — the shapes the WebSocket layer, REST
 * hydration, and every panel share. One definition each; import from
 * '@/stores/useDashboardStore' (which re-exports this module).
 */
import type { NotificationSeverity } from '@/constants/notifications'

export type { NotificationSeverity } from '@/constants/notifications'

export interface AgentLog {
  agent_name: string
  event_type?: string
  message?: string
  trace_id?: string
  timestamp: string
  confidence?: number
  latency_ms?: number
  primary_edge?: string
  stream?: unknown
  message_id?: unknown
  data?: unknown
  id?: string | number
  agent?: string
  action?: string
  symbol?: string
  [key: string]: unknown
}

export interface Order {
  symbol: string
  pnl: number
  side: 'long' | 'short'
  quantity: number
  entry_price: number
  current_price: number
  timestamp: string
  pnl_percent?: number
  order_id?: string | number
  [key: string]: unknown
}

export interface Position {
  symbol: string
  side: 'long' | 'short'
  quantity: number
  entry_price: number
  current_price: number
  pnl: number
  pnl_percent?: number
  [key: string]: unknown
}

export interface SystemMetric {
  metric_name: string
  value: number
  id?: string | number
  [key: string]: unknown
}

export interface LearningEvent {
  type: string
  timestamp: string
  id?: string | number
  [key: string]: unknown
}

export interface NotificationDisplayItem {
  label: string
  value: string
  tone?: string
}

export interface NotificationDisplayBadge {
  label: string
  tone?: string
}

export interface NotificationDisplay {
  kind?: string
  tone?: string
  icon?: string
  title?: string
  subtitle?: string
  status_label?: string
  badges?: NotificationDisplayBadge[]
  facts?: NotificationDisplayItem[]
  meta?: NotificationDisplayItem[]
}

export interface Notification {
  id: string
  severity: NotificationSeverity
  title?: string
  body?: string
  message: string
  notification_type: string
  stream_source?: string
  action?: string
  symbol?: string
  qty?: number | null
  fill_price?: number | null
  notional?: number | null
  pnl?: number | null
  pnl_percent?: number | null
  order_id?: string | number | null
  trace_id?: string
  state?: 'open' | 'resolved'
  delivery?: Record<string, unknown>
  display?: NotificationDisplay
  timestamp: string
}

export type ProposalStatus = 'pending' | 'approved' | 'rejected'
// Mirrors backend api.constants.ProposalType plus the informational
// "challenger_result" event (emitted as a raw type by ChallengerAgent).
export type ProposalType =
  | 'parameter_change'
  | 'code_change'
  | 'regime_adjustment'
  | 'signal_weight_reduction'
  | 'agent_suspension'
  | 'agent_retirement'
  | 'new_agent'
  | 'tool_governance'
  | 'prompt_evolution'
  | 'challenger_result'
  | 'challenger_promotion'

export interface Proposal {
  id: string
  proposal_type: ProposalType
  content: string
  requires_approval: boolean
  reflection_trace_id?: string
  confidence?: number
  timestamp: string
  status: ProposalStatus
  /** True once the ProposalApplier has actually applied it (auto or approved). */
  applied?: boolean
  applied_at?: string | null
  // Our branch fields (from events table / WS proposals stream)
  symbol?: string | null
  action?: string | null
  grade_score?: number | null
  bias?: string | null
  buys?: number | null
  sells?: number | null
  strategy_name?: string | null
  trace_id?: string | null
  created_at?: string | null
  source?: string | null
  /** Human-readable outcome the applier recorded (e.g. "config PR opened …"). */
  message?: string | null
  /** Clickable artifact link — the GitHub issue/PR URL the proposal produced. */
  pr_url?: string | null
}

export interface PriceData {
  price: number
  change: number
  changePercent?: number
  previousPrice?: number
  updatedAt?: string
  /** Real L1 best bid/ask from the poller cache (two-sided quotes only). */
  bid?: number
  ask?: number
  [key: string]: unknown
}

export interface StreamStat {
  count: number
  lastMessageTimestamp: string | null
}

/** One agent heartbeat row (Redis agent:status:{name}) as the dashboard receives it. */
export interface AgentHeartbeat {
  name: string
  status: string
  event_count: number
  last_event: string
  last_seen: number
  last_seen_at?: string
  source?: string
  seconds_ago: number
  last_grade_score?: number
}

export interface WsDiagnostics {
  reconnectAttempts: number
  messageRate: number
  lastError: string | null
}

export interface TradeFeedItem {
  id: string
  symbol: string
  side: 'buy' | 'sell'
  qty: number | null
  entry_price: number | null
  exit_price: number | null
  pnl: number | null
  pnl_percent: number | null
  order_id: string | null
  execution_trace_id: string | null
  signal_trace_id: string | null
  grade: string | null
  grade_score: number | null
  grade_label: string | null
  status: string
  filled_at: string | null
  graded_at: string | null
  reflected_at: string | null
  created_at: string | null
}

/** Normalize a raw trade dict (from REST or WS) into a well-typed TradeFeedItem. */
/**
 * One completed round-trip (realized PnL) from `/dashboard/state`'s
 * `closed_trades` block. Distinct from TradeFeedItem (per-fill lifecycle rows):
 * this is the verifiable "past trades" ledger behind the headline P&L.
 */
export interface ClosedTrade {
  symbol: string
  side: 'buy' | 'sell'
  qty: number | null
  entry_price: number | null
  exit_price: number | null
  pnl: number | null
  pnl_percent: number | null
  /** ISO string when the round-trip closed (backend sends filled_at or timestamp). */
  closed_at: string | null
}

export interface AgentInstance {
  id: string
  instance_key: string
  pool_name: string
  status: 'active' | 'retired'
  started_at: string | null
  retired_at: string | null
  event_count: number
  uptime_seconds: number
}

export interface PerformanceSummary {
  total_pnl: number
  total_trades: number
  win_rate: number
  avg_win: number
  avg_loss: number
  best_trade: number
  worst_trade: number
}

// Live PnL breakdown from GET /pnl (PaperBroker-sourced). Distinct from
// PerformanceSummary: this carries realized vs unrealized split + open-position
// count straight from the broker, updated on every poll/reconnect.
export interface PnlSummary {
  realized_pnl: number
  unrealized_pnl: number
  total_pnl: number
  closed_trades: number
  winning_trades: number
  win_rate_percent: number
  open_positions: number
}

export interface DailyPnl {
  day: string
  pnl: number
  trade_count: number
  wins: number
  losses: number
  avg_pnl: number
}

export interface RecentEvent {
  stream: string
  msgId: string
  timestamp: string
  // What the event was *about* — carried through so the Live Activity feed can
  // show "BTC/USD · $60,781.58" instead of a bare, indistinguishable row.
  symbol?: string | null
  price?: number | null
  change?: number | null
  eventType?: string | null
}

export type DashboardData = {
  system_metrics?: SystemMetric[]
  orders?: Order[]
  agent_logs?: AgentLog[]
  learning_events?: LearningEvent[]
  risk_alerts?: Array<Record<string, unknown>>
  signals?: Array<Record<string, unknown>>
  positions?: Position[]
  prices?: Record<string, PriceData>
  proposals?: Array<Record<string, unknown>>
  trade_feed?: TradeFeedItem[]
  /** Completed round-trips (newest first) — backs the Closed Trades panel. */
  closed_trades?: Array<Record<string, unknown>>
  notifications?: Array<Record<string, unknown>>
  ic_weights?: Record<string, number>
  agent_statuses?: Array<Record<string, unknown>>
  timestamp: string
  /** Runtime persistence mode — "db" | "in_memory_fallback". Present when backend is in memory mode. */
  mode?: string
  /** True when DB is unavailable and the system is operating from in-memory state. */
  degraded_mode?: boolean
  /** Machine-readable reason: "db_unavailable" | "redis_unavailable" */
  degraded_reason?: string
}

export type PriceRecord = Record<string, PriceData>

/** Price data shape returned by the REST price cache. */
export interface CachedPriceData {
  price: string | number;
  bid?: string | number;
  ask?: string | number;
  timestamp: string;
  source?: string;
}


