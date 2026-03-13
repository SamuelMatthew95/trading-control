export type AgentState = 'running' | 'idle' | 'failed';

export interface AgentView {
  name: string;
  status: AgentState;
  updated_at?: string;
  health?: string;
  current_task?: string;
  last_task?: string;
  latency_ms?: number;
  error?: string;
}

export interface MonitoringOverview {
  uptime_seconds: number;
  total_requests: number;
  total_errors: number;
  error_rate: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  recent_events: Array<Record<string, unknown>>;
  agent_status: AgentView[];
}

export interface TradingStats {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
}

export interface TradeRow {
  id: number;
  date: string;
  asset: string;
  direction: string;
  entry: number;
  stop: number;
  target: number;
  rr_ratio: number;
  pnl?: number;
  outcome: string;
}
