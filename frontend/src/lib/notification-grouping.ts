/**
 * Notification grouping helpers.
 *
 * Pure functions so they can be tested without a DOM or React context.
 */

export interface GroupableNotification {
  id: string
  notification_type?: string | null
  symbol?: string | null
  action?: string | null
  title?: string | null
  timestamp?: string | null
  severity?: string | null
}

export interface NotificationGroup<T extends GroupableNotification> {
  /** Representative notification (latest by timestamp). */
  latest: T
  /** Total count of notifications in this group. */
  count: number
}

/**
 * Build a stable dedup key for grouping notifications.
 *
 * Notifications with the same type + symbol + action are considered the same
 * logical event. Notifications without a type fall back to keying on `title`.
 */
export function notificationGroupKey(n: GroupableNotification): string {
  const type = n.notification_type ?? 'unknown'
  const symbol = n.symbol ?? ''
  const action = n.action ?? ''
  return `${type}|${symbol}|${action}`
}

/**
 * Group an array of notifications by type+symbol+action.
 *
 * Within each group the notification with the latest `timestamp` is kept as the
 * representative. The returned array preserves the order of the first occurrence
 * of each group key (most-recent-first when the input is sorted descending).
 *
 * @param notifications - Input notifications, typically sorted newest-first.
 * @param maxGroups     - Maximum number of groups to return (default: unlimited).
 */
export function groupNotifications<T extends GroupableNotification>(
  notifications: T[],
  maxGroups?: number,
): NotificationGroup<T>[] {
  const groupMap = new Map<string, NotificationGroup<T>>()
  const order: string[] = []

  for (const n of notifications) {
    const key = notificationGroupKey(n)
    const existing = groupMap.get(key)
    if (!existing) {
      groupMap.set(key, { latest: n, count: 1 })
      order.push(key)
    } else {
      existing.count += 1
      // Keep the newer notification as the representative.
      const existingTs = existing.latest.timestamp ?? ''
      const incomingTs = n.timestamp ?? ''
      if (incomingTs > existingTs) {
        existing.latest = n
      }
    }
  }

  const groups = order.map((key) => groupMap.get(key)!)
  return maxGroups != null ? groups.slice(0, maxGroups) : groups
}

/**
 * Return true if the notification looks like a startup or system-internal event
 * that should be categorised differently from operator-facing trade notifications.
 *
 * These are demoted to a lower-priority display in the feed (not hidden).
 */
export function isSystemInternalNotification(n: GroupableNotification): boolean {
  const type = n.notification_type ?? ''
  return (
    type.startsWith('system.') ||
    type === 'db_unavailable' ||
    type === 'redis_unavailable' ||
    type === 'startup' ||
    type.includes('connection')
  )
}
