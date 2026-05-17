/**
 * Derives the agent activity display state from observable signals.
 *
 * Pure function — no side effects, no DOM access. Extracted for testability.
 */

export type ActivityIndicator = 'live' | 'waiting' | 'offline'

/**
 * Determine whether agent activity is LIVE, WAITING, or OFFLINE.
 *
 * - LIVE    : at least one recent log entry with a fresh timestamp (within freshnessMs).
 * - WAITING : WebSocket is connected but no fresh log activity.
 * - OFFLINE : WebSocket is disconnected.
 *
 * @param latestTimestamp - ISO timestamp string of the most recent log entry, or null.
 * @param wsConnected     - Whether the WebSocket connection is established.
 * @param freshnessMs     - Age threshold in milliseconds below which a log is "fresh".
 *                          Defaults to 60 000 ms (1 minute).
 * @param nowMs           - Current time in milliseconds (injectable for tests).
 */
export function deriveActivityIndicator(
  latestTimestamp: string | null | undefined,
  wsConnected: boolean,
  freshnessMs = 60_000,
  nowMs = Date.now(),
): ActivityIndicator {
  if (latestTimestamp) {
    const d = new Date(latestTimestamp)
    if (!isNaN(d.getTime()) && nowMs - d.getTime() < freshnessMs) {
      return 'live'
    }
  }
  return wsConnected ? 'waiting' : 'offline'
}
