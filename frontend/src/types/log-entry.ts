/**
 * Shared log entry type used across log viewer components.
 *
 * source  — present in LiveLogs and legacy logs page (identifies which system component emitted the log)
 * details — present in LogViewer (optional expanded detail / stack trace)
 */
export interface LogEntry {
  id: string
  timestamp: string
  level: 'info' | 'warning' | 'error' | 'success'
  message: string
  source?: string
  details?: string
}

export type LogLevel = LogEntry['level']
