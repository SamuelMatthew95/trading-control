export const NOTIFICATION_SEVERITIES = ['success', 'info', 'warning', 'critical'] as const
export type NotificationSeverity = (typeof NOTIFICATION_SEVERITIES)[number]

export const NOTIFICATION_FALLBACKS = {
  severity: 'info' as NotificationSeverity,
  icon: 'bell',
  notificationType: 'system',
  emptyTimestamp: '--',
} as const
