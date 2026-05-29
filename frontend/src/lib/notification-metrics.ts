/**
 * Notification headline metrics for the dashboard.
 *
 * The stored notification list is a capped backlog (max 200), so its raw length
 * is a poor "what's happening now" number — a freshly opened app shows 200 even
 * when nothing new arrived. These helpers derive the *recent* count and a
 * last-activity label instead.
 */
import { parseTimestampMs } from '@/lib/formatters'

/** Count notifications whose timestamp falls within `windowMs` of now. */
export function countRecentNotifications(
  notifications: Array<{ timestamp?: string }>,
  windowMs: number,
): number {
  const cutoff = Date.now() - windowMs
  return notifications.reduce((count, item) => {
    const ms = parseTimestampMs(item.timestamp)
    return ms != null && ms >= cutoff ? count + 1 : count
  }, 0)
}

/** Label for the newest notification's time, or a placeholder when there is none. */
export function lastNotificationLabel(notifications: Array<{ timestamp?: string }>): string {
  const ms = parseTimestampMs(notifications[0]?.timestamp)
  return ms != null ? `Last: ${new Date(ms).toLocaleTimeString()}` : 'No activity yet'
}
