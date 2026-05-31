/**
 * Shared formatting helpers.
 *
 * One canonical implementation each — import from here, never re-define locally.
 */

/**
 * Epoch threshold for distinguishing seconds from milliseconds timestamps.
 *
 * Unix timestamps in seconds stay below 10^10 until the year 2286. Any numeric
 * value above this boundary is already in milliseconds; values below are
 * multiplied by 1 000. This resolves the common API ambiguity where different
 * fields use seconds vs milliseconds without annotation.
 */
export const EPOCH_MS_THRESHOLD = 10_000_000_000

/**
 * Convert any unknown value to a finite number, or return null.
 *
 * Accepts numbers and numeric strings. Returns null for NaN, ±Infinity, null,
 * undefined, empty strings, and non-numeric strings.
 */
export function toFiniteNum(v: unknown): number | null {
  if (v == null || v === '') return null
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : null
}

/**
 * Read a field from a loosely-typed object (API row / store record) by key,
 * returning `undefined` when the object is not a plain object or the key is
 * absent. One canonical replacement for the scattered
 * `(x as Record<string, unknown>)?.field` casts — safe on null/array/primitive.
 */
export function getField(obj: unknown, key: string): unknown {
  if (obj == null || typeof obj !== 'object' || Array.isArray(obj)) return undefined
  return (obj as Record<string, unknown>)[key]
}

/**
 * Read the first present field from a list of candidate keys as a string,
 * coalescing across alias names (e.g. `agent_name` | `agent` | `source`).
 * Returns '' when none are present, so callers never handle null.
 */
export function getStr(obj: unknown, ...keys: string[]): string {
  for (const key of keys) {
    const v = getField(obj, key)
    if (v != null && v !== '') return String(v)
  }
  return ''
}

/**
 * Parse any timestamp-like value to epoch milliseconds, or return null.
 *
 * Handles: Date objects, numeric ms, numeric seconds (via EPOCH_MS_THRESHOLD),
 * ISO-8601 strings, and numeric strings.
 */
export function parseTimestampMs(value: unknown): number | null {
  if (!value) return null
  if (value instanceof Date) {
    const t = value.getTime()
    return Number.isNaN(t) ? null : t
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || value <= 0) return null
    const ms = value > EPOCH_MS_THRESHOLD ? value : value * 1000
    return Number.isFinite(ms) ? ms : null
  }
  const raw = String(value).trim()
  if (!raw || raw === '0') return null
  if (/^\d+(\.\d+)?$/.test(raw)) {
    const num = Number(raw)
    if (!Number.isFinite(num) || num <= 0) return null
    const ms = num > EPOCH_MS_THRESHOLD ? num : num * 1000
    return Number.isNaN(new Date(ms).getTime()) ? null : ms
  }
  const parsed = Date.parse(raw)
  return Number.isNaN(parsed) || parsed <= 0 ? null : parsed
}

/**
 * Format a dollar amount (unsigned).
 *
 * Returns '--' for null/undefined/non-finite so that a missing P&L value does
 * not render as '$0.00' (break-even) in the UI. Uses the absolute value —
 * prepend a sign yourself when directional display is needed.
 */
export function formatUSD(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '--'
  return `$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/**
 * Format a signed dollar amount.
 *
 * Returns '--' for null/undefined/non-finite. Near-zero values (|v| < $0.005)
 * render as '$0.00' to prevent the '-$0.00' display artifact that arises when
 * a tiny negative rounds to zero at 2 decimal places.
 */
export function signedUSD(value: number | null | undefined): string {
  if (value == null || isNaN(value) || !isFinite(value)) return '--'
  const abs = Math.abs(value)
  if (abs < 0.005) return '$0.00'
  return `${value > 0 ? '+' : '-'}$${abs.toFixed(2)}`
}

/**
 * Format a timestamp as a human-readable relative age ("3m ago", "2h ago").
 *
 * Accepts an ISO string, a Date, or null/undefined. Returns an empty string
 * for invalid or missing input so callers can use it in template expressions
 * without a separate null-guard.
 */
export function formatTimeAgo(v: string | Date | null | undefined): string {
  if (!v) return ''
  const d = typeof v === 'string' ? new Date(v) : v
  if (isNaN(d.getTime())) return ''
  const seconds = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

/**
 * Render a value for display, collapsing missing/invalid input to '--' so the
 * UI never shows `null`, `undefined`, `NaN`, or an empty string.
 */
export function sanitizeValue(value: string | number | boolean | null | undefined): string {
  if (value === undefined || value === null || value === '') return '--'
  if (typeof value === 'number' && (isNaN(value) || !isFinite(value))) return '--'
  if (typeof value === 'boolean') return value ? 'True' : 'False'
  return String(value)
}

/** Format a timestamp as a local clock time ("3:45:01 PM"); '--' when missing/invalid. */
export function formatTimestamp(value?: string | null): string {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleTimeString()
}
