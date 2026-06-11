/**
 * Pure wire-shape normalizers for the dashboard store. No state in here —
 * everything is unit-testable in isolation.
 */
import { NOTIFICATION_FALLBACKS, NOTIFICATION_SEVERITIES, type NotificationSeverity } from '@/constants/notifications'
import { EPOCH_MS_THRESHOLD } from '@/lib/formatters'
import type { ClosedTrade, Notification, NotificationDisplay, TradeFeedItem } from './types'

export function normalizeTradeFeedItem(raw: Record<string, unknown>): TradeFeedItem {
  const toNum = (v: unknown): number | null => (typeof v === 'number' && isFinite(v) ? v : null)
  const toStr = (v: unknown): string | null => (v != null ? String(v) : null)
  return {
    id: String(raw.id ?? Date.now()),
    symbol: String(raw.symbol ?? ''),
    side: raw.side === 'sell' ? 'sell' : 'buy',
    qty: toNum(raw.qty),
    entry_price: toNum(raw.entry_price),
    exit_price: toNum(raw.exit_price),
    pnl: toNum(raw.pnl),
    pnl_percent: toNum(raw.pnl_percent),
    order_id: toStr(raw.order_id),
    execution_trace_id: toStr(raw.execution_trace_id),
    signal_trace_id: toStr(raw.signal_trace_id),
    grade: toStr(raw.grade),
    grade_score: toNum(raw.grade_score),
    grade_label: toStr(raw.grade_label),
    status: String(raw.status ?? 'filled'),
    filled_at: toStr(raw.filled_at),
    graded_at: toStr(raw.graded_at),
    reflected_at: toStr(raw.reflected_at),
    created_at: String(raw.created_at ?? raw.timestamp ?? new Date().toISOString()),
  }
}

function normalizeNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const cast = Number(value)
  return Number.isFinite(cast) ? cast : null
}

function buildDeterministicNotificationId(raw: Record<string, unknown>): string {
  const basis = [
    raw.notification_id,
    raw.id,
    raw.trace_id,
    raw.timestamp,
    raw.notification_type,
    raw.title,
    raw.message,
    raw.body,
    raw.symbol,
    raw.action,
  ]
    .map((v) => String(v ?? ""))
    .join("|")
  if (!basis) return "0-unknown"
  let hash = 5381
  for (let i = 0; i < basis.length; i += 1) {
    hash = ((hash << 5) + hash) ^ basis.charCodeAt(i)
  }
  return `${Math.abs(hash >>> 0)}-det`
}

export function normalizeStoredNotification(input: unknown): Notification | null {
  if (!input || typeof input !== 'object') return null
  const raw = input as Record<string, unknown>
  const severity = String(raw.severity || NOTIFICATION_FALLBACKS.severity).toLowerCase()
  const normalizedSeverity: NotificationSeverity = (
    NOTIFICATION_SEVERITIES as readonly string[]
  ).includes(severity)
    ? (severity as NotificationSeverity)
    : NOTIFICATION_FALLBACKS.severity

  const display =
    raw.display && typeof raw.display === 'object' && !Array.isArray(raw.display)
      ? (raw.display as NotificationDisplay)
      : undefined
  const message = String(raw.message || raw.body || display?.subtitle || raw.title || '').trim()
  if (!message) return null

  // Prefer the backend's stable notification_id so the same fill survives a
  // page reload without being treated as a new notification.
  const stableId = raw.notification_id ?? raw.id ?? buildDeterministicNotificationId(raw)
  const notification: Notification = {
    id: String(stableId),
    severity: normalizedSeverity,
    title: raw.title ? String(raw.title) : (raw.body ? String(raw.body) : undefined),
    message,
    notification_type: String(raw.notification_type || NOTIFICATION_FALLBACKS.notificationType),
    stream_source: raw.stream_source ? String(raw.stream_source) : undefined,
    action: raw.action ? String(raw.action) : undefined,
    symbol: raw.symbol ? String(raw.symbol) : undefined,
    qty: normalizeNumber(raw.qty),
    fill_price: normalizeNumber(raw.fill_price),
    notional: normalizeNumber(raw.notional),
    pnl: normalizeNumber(raw.pnl),
    pnl_percent: normalizeNumber(raw.pnl_percent),
    order_id: raw.order_id == null ? null : String(raw.order_id),
    trace_id: raw.trace_id ? String(raw.trace_id) : undefined,
    state: String(raw.state || 'open').toLowerCase() === 'resolved' ? 'resolved' : 'open',
    delivery:
      raw.delivery && typeof raw.delivery === 'object' && !Array.isArray(raw.delivery)
        ? (raw.delivery as Record<string, unknown>)
        : undefined,
    display,
    timestamp: String(raw.timestamp || new Date().toISOString()),
  }

  return notification
}


/** Normalize a raw closed-trade dict (REST snapshot) into a well-typed ClosedTrade. */
export function normalizeClosedTrade(raw: Record<string, unknown>): ClosedTrade {
  // Memory-mode rows carry an epoch-seconds `timestamp`; DB rows carry ISO `filled_at`.
  const closedAtRaw = raw.filled_at ?? raw.timestamp ?? null
  const closedAtMs =
    typeof closedAtRaw === 'number' && Number.isFinite(closedAtRaw)
      ? (closedAtRaw > EPOCH_MS_THRESHOLD ? closedAtRaw : closedAtRaw * 1000)
      : null
  return {
    symbol: String(raw.symbol ?? ''),
    side: raw.side === 'sell' ? 'sell' : 'buy',
    qty: normalizeNumber(raw.qty),
    entry_price: normalizeNumber(raw.entry_price),
    exit_price: normalizeNumber(raw.exit_price),
    pnl: normalizeNumber(raw.pnl),
    pnl_percent: normalizeNumber(raw.pnl_percent),
    closed_at:
      closedAtMs != null
        ? new Date(closedAtMs).toISOString()
        : closedAtRaw != null
          ? String(closedAtRaw)
          : null,
  }
}
