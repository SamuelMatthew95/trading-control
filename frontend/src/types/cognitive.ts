// Types mirroring cognitive.loop.CognitiveLoop.snapshot() — the single
// read-only data source for the Cognitive dashboard (driven by the event stream).

export interface CognitiveConfig {
  version: number
  weights: Record<string, number>
  buy_threshold: number
  sell_threshold: number
  risk: Record<string, number>
  // Present on live config versions: why this directive was promoted.
  rationale?: string
}

export interface AgentSpec {
  name: string
  role: string
  emits: string
  description: string
}

export interface DecisionPayload {
  action: string
  score: number
  breakdown: Record<string, number>
  buy_threshold: number
  sell_threshold: number
  trace_id?: string
  seq?: number
}

export interface AgentGrade {
  subject_id: string
  grade: string
  score: number
  samples?: number
  correct_rate?: number
  contribution?: number
}

export interface TradeGrade {
  subject_id: string
  grade: string
  score: number
  direction_grade?: string
  risk_grade?: string
  execution_grade?: string
  timing_grade?: string
  trace_id?: string
}

export interface Observation {
  observation: string
  confidence: number
  signal: string
  direction: string
  evidence: Record<string, unknown>
}

export interface Counterfactual {
  chosen_action: string
  chosen_pnl_pct: number
  alternatives: Record<string, number>
  best_action: string
  best_pnl_pct: number
  regret_pct: number
  was_best: boolean
  trace_id?: string
}

export interface DriftAlert {
  metric: string
  direction: string
  recent: number
  baseline: number
  delta: number
}

export interface ProposalPayload {
  proposal_id: string
  proposal_type: string
  target: string
  old_value: unknown
  new_value: unknown
  change: unknown
  reason: string
  expected_impact: string
  diff: Record<string, { old: unknown; new: unknown }>
}

export interface ChallengerVerdict {
  approved: boolean
  risk_score: number
  reasons: string[]
  checks: Record<string, boolean>
}

export interface BacktestDelta {
  pnl_delta: number
  sharpe_delta: number
  drawdown_delta: number
  false_positive_rate_delta: number
  improves: boolean
}

export interface QueueEntry {
  proposal: ProposalPayload
  status: string
  verdict: ChallengerVerdict | null
  delta: BacktestDelta | null
  pull_request: { branch: string; title: string; body: string } | null
  proposal_grade: { grade: string; score: number } | null
}

export interface ConfigVersion {
  version: number
  config: CognitiveConfig
  grade: { grade: string; score: number } | null
}

export interface TradeTrace {
  trace_id: string
  signals: {
    news: Record<string, unknown> | null
    tech: Record<string, unknown> | null
    macro: Record<string, unknown> | null
    risk: Record<string, unknown> | null
  }
  reasoning: Record<string, unknown> | null
  decision: DecisionPayload | null
  risk_gate: Record<string, unknown> | null
  execution: Record<string, unknown> | null
  outcome: Record<string, unknown> | null
  counterfactual: Counterfactual | null
  grade: TradeGrade | null
  event_count: number
}

export interface CognitiveHealth {
  event_stream: { total_events: number; last_seq: number; by_type: Record<string, number> }
  agents: Record<string, { status: string; events: number; last_seq: number }>
  decision: {
    signals_received: Record<string, number>
    decisions_made: number
    executions: number
    last_decision: string | null
  }
  proposal_pipeline: {
    generated: number
    backtested: number
    approved: number
    rejected: number
    pr_requests: number
    merged: number
  }
  learning: {
    trades_closed: number
    trades_graded: number
    ungraded: number
    observations: number
  }
}

export interface CognitiveSnapshot {
  config: CognitiveConfig
  agents_roster: AgentSpec[]
  // Latest live activity keyed by agent name (real pipeline) — or the sim's
  // news/tech/macro/risk keys under ?demo=true. Generic map so both work.
  live_agents: Record<string, Record<string, unknown> | null>
  reasoning: Array<Record<string, unknown>>
  decision: {
    latest: DecisionPayload | null
    recent: DecisionPayload[]
    weights: Record<string, number>
    buy_threshold: number
    sell_threshold: number
  }
  proposals: QueueEntry[]
  challenger: Array<ChallengerVerdict & { proposal_id?: string }>
  learning: {
    importance: Record<string, Record<string, number>>
    agent_grades: AgentGrade[]
    observations: Observation[]
    trade_grades: TradeGrade[]
    mean_regret_pct?: number
    best_action_rate?: number
  }
  counterfactuals: Counterfactual[]
  drift: {
    alerts: DriftAlert[]
    monitor: {
      window: number
      min_samples: number
      metrics: Record<string, { samples: number; latest: number | null }>
    }
  }
  evolution: {
    config_versions: ConfigVersion[]
    proposal_success_rates: Record<string, { attempts: number; successes: number; success_rate: number }>
    agent_grades: AgentGrade[]
  }
  health: CognitiveHealth
  traces: TradeTrace[]
  event_count: number
}

export interface CognitiveEvent {
  seq: number
  type: string
  payload: Record<string, unknown>
  trace_id: string
  source: string
  ts: string
}
