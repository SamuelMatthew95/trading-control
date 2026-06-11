/**
 * UI copy registry — user-facing strings live here, not inline in JSX.
 *
 * One place to keep tone-of-voice consistent, fix wording, or (later)
 * localize. Keyed structurally: `UI_COPY.<surface>.<string>`. Components
 * compose dynamic fragments around these constants; fully dynamic sentences
 * (interpolating live values) stay in the component but should reuse the
 * shared sentence stems from here where one exists.
 */

/** Empty-state explanations for the trade feed, keyed by backend reason code. */
export const TRADE_FEED_EMPTY_LABELS: Record<string, string> = {
  db_degraded: 'DB unavailable — fills will appear when DB reconnects',
  no_orders_executed: 'No orders executed yet — decisions are being evaluated',
  lifecycle_not_persisted: 'Orders placed but lifecycle rows are pending',
  no_executable_intents: 'Pipeline active — no executable intents yet',
  default: 'No fills yet — waiting for executed trades',
}

export const UI_COPY = {
  activityIndicator: {
    live: 'LIVE',
    waiting: 'WAITING',
    offline: 'OFFLINE',
  },
  empty: {
    activity: 'No activity yet — events stream in here as the pipeline runs.',
    agents: 'No active agents',
    decisions: 'No buy/sell decisions yet',
    learningOutcomes: 'No fills yet — learning outcomes appear after execution and grading.',
    proposals: 'No strategy proposals yet — evidence appears here after reflection.',
    learningEvents: 'No learning-agent events have streamed yet.',
  },
  banners: {
    reconnecting: 'Reconnecting to live feed…',
    memoryModeTitle: 'Memory mode',
    memoryModeBody:
      'Data is ephemeral and will be lost on restart. Trade history and grades are stored in-process only.',
    memoryModeDbReason: ': PostgreSQL unreachable',
  },
  trace: {
    emptyTrace:
      "No pipeline trace was recorded for this event. System notifications and rule-based fallback decisions don't flow through the agent pipeline, and in memory mode (no database) trace history clears on restart — only live, in-session traces are available here.",
    loadError: 'Could not load this trace — the dashboard API did not respond.',
    loading: 'Loading…',
  },
} as const
