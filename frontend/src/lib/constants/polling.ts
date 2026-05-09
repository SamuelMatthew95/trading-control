/**
 * Polling cadences — every `setInterval` in the dashboard reads from here.
 *
 * Why one file: most of these used to be local `const REFRESH_MS = 15_000`
 * declarations sprinkled across components. Tuning the dashboard's load on
 * the backend then meant grepping for every value. Co-locating the cadences
 * here makes the trade-off explicit (more frequent = fresher UI, more API
 * load) and trivial to adjust.
 */

/** /dashboard/state poll while the WebSocket is disconnected. */
export const DASHBOARD_STATE_POLL_MS = 15_000

/** Most /dashboard and /learning REST endpoints poll at this cadence. */
export const DASHBOARD_DATA_POLL_MS = 30_000

/** /llm/health quick poll — surfaces LLM outages within ~5s. */
export const LLM_HEALTH_POLL_MS = 5_000

/** /signals operator-action sidebar poll — low-frequency since it's manual. */
export const SIGNALS_POLL_MS = 60_000

/**
 * /learning/* refresh used by the standalone LearningDashboard panel.
 * Re-exported as `LEARNING_REFRESH_MS` for callers that already use that
 * name (kept stable to avoid a cross-file rename).
 */
export const LEARNING_DASHBOARD_POLL_MS = 15_000
