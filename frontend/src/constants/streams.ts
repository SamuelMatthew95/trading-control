/**
 * Redis Stream names — mirrors the `STREAM_*` constants in `api/constants.py`.
 *
 * These are the agent-to-agent event-bus channel names. The frontend reads
 * per-stream counters from the store's `streamStats`; never key into that map
 * with a raw string — import the constant so the channel name has one home.
 */

export const STREAM_MARKET_TICKS = 'market_ticks'
export const STREAM_MARKET_EVENTS = 'market_events'
export const STREAM_SIGNALS = 'signals'
export const STREAM_DECISIONS = 'decisions'
export const STREAM_ORDERS = 'orders'
export const STREAM_EXECUTIONS = 'executions'
export const STREAM_AGENT_LOGS = 'agent_logs'
export const STREAM_AGENT_GRADES = 'agent_grades'
export const STREAM_RISK_ALERTS = 'risk_alerts'
export const STREAM_NOTIFICATIONS = 'notifications'
