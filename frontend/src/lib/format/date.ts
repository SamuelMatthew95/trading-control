/**
 * Date / time formatting primitives.
 *
 * Accepts ISO strings, JS Dates, and unix epochs (seconds OR milliseconds —
 * auto-detected by magnitude). Returns "—" for any unparseable input rather
 * than crashing the render path.
 */

import { MISSING } from './number'

const SECONDS_TO_MS_THRESHOLD = 10_000_000_000 // > Sat Nov 20 2286 in seconds

/** Parses anything date-shaped into a Date or null. */
export function parseTimestamp(value: unknown): Date | null {
  if (value == null) return null
  if (value instanceof Date) {
    const t = value.getTime()
    return Number.isNaN(t) || t <= 0 ? null : value
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || value <= 0) return null
    const ms = value > SECONDS_TO_MS_THRESHOLD ? value : value * 1000
    const d = new Date(ms)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const raw = String(value).trim()
  if (!raw || raw === '0') return null
  if (/^\d+(\.\d+)?$/.test(raw)) {
    const num = Number(raw)
    if (!Number.isFinite(num) || num <= 0) return null
    const ms = num > SECONDS_TO_MS_THRESHOLD ? num : num * 1000
    const d = new Date(ms)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const d = new Date(raw)
  if (Number.isNaN(d.getTime()) || d.getTime() <= 0) return null
  return d
}

/** Locale-aware time of day ("10:23:45 AM"). */
export function formatTimestamp(value: unknown): string {
  const d = parseTimestamp(value)
  if (!d) return MISSING
  return d.toLocaleTimeString()
}

/** Relative time ago ("3s ago", "5m ago", "2h ago", "4d ago"). */
export function formatTimeAgo(value: unknown, now: number = Date.now()): string {
  const d = parseTimestamp(value)
  if (!d) return MISSING
  const seconds = Math.max(0, Math.floor((now - d.getTime()) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

/** Compact age from milliseconds: "12s", "3m", "2h". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return MISSING
  const sec = Math.floor(ms / 1000)
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h`
  return `${Math.floor(hr / 24)}d`
}

/** Uptime in human form ("45s", "12m", "3h 25m"). */
export function formatUptime(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return MISSING
  if (seconds < 60) return `${Math.floor(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return `${hours}h ${remainingMinutes}m`
}
