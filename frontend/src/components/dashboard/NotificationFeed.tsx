'use client'

import type { ComponentType } from 'react'
import { EmptyState } from '@/components/ui/empty-state'
import {
  ArrowDownRight,
  ArrowUpRight,
  AlertCircle,
  AlertTriangle,
  Bell,
  BellRing,
  Info,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { parseTimestampMs } from '@/lib/formatters'
import type { Notification } from '@/stores/useCodexStore'
import { NOTIFICATION_FALLBACKS } from '@/constants/notifications'
import { groupNotifications } from '@/lib/notification-grouping'

const cardClass =
  'rounded-lg border border-slate-300 bg-white p-4 transition-colors duration-150 hover:border-slate-400 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-600 sm:p-5'
const sectionTitleClass = 'text-xs font-semibold uppercase font-sans text-slate-500 dark:text-slate-400'
const mutedClass = 'text-xs font-sans text-slate-500 dark:text-slate-400'

// The Redis-backed notifications list survives restarts, so without an age cap a
// 3-day-old fill sits at the top of the feed and makes a live system look stale.
// Drop anything older than this from the live feed (the count below still
// reflects the live set; the full list remains queryable via the REST history).
// Unparseable timestamps are kept — we can't prove they're stale.
const NOTIFICATION_LIVE_WINDOW_MS = 3_600_000 // 1 hour

function isLiveNotification(n: Notification, cutoffMs: number): boolean {
  const ts = parseTimestampMs(n.timestamp)
  return ts == null || ts >= cutoffMs
}

const iconByName: Record<string, ComponentType<{ className?: string }>> = {
  'arrow-down-right': ArrowDownRight,
  'arrow-up-right': ArrowUpRight,
  alert: AlertCircle,
  bell: BellRing,
  info: Info,
  warning: AlertTriangle,
}

const toneStyles: Record<
  string,
  {
    card: string
    icon: string
    badge: string
    text: string
    dot: string
    border: string
  }
> = {
  buy: {
    card: 'border-emerald-500/40 bg-emerald-500/5 dark:border-emerald-500/30 dark:bg-emerald-500/5',
    icon: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
    badge: 'border border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
    text: 'text-emerald-700 dark:text-emerald-300',
    dot: 'bg-emerald-500',
    border: 'border-l-emerald-500',
  },
  sell: {
    card: 'border-rose-500/40 bg-rose-500/5 dark:border-rose-500/30 dark:bg-rose-500/5',
    icon: 'bg-rose-500/15 text-rose-600 dark:text-rose-400',
    badge: 'border border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300',
    text: 'text-rose-700 dark:text-rose-300',
    dot: 'bg-rose-500',
    border: 'border-l-rose-500',
  },
  gain: {
    card: 'border-emerald-500/40 bg-emerald-500/5 dark:border-emerald-500/30',
    icon: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
    badge: 'border border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
    text: 'text-emerald-700 dark:text-emerald-300',
    dot: 'bg-emerald-500',
    border: 'border-l-emerald-500',
  },
  loss: {
    card: 'border-rose-500/40 bg-rose-500/5 dark:border-rose-500/30',
    icon: 'bg-rose-500/15 text-rose-600 dark:text-rose-400',
    badge: 'border border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300',
    text: 'text-rose-700 dark:text-rose-300',
    dot: 'bg-rose-500',
    border: 'border-l-rose-500',
  },
  critical: {
    card: 'border-rose-600/50 bg-rose-500/8 dark:border-rose-600/40',
    icon: 'bg-rose-500/15 text-rose-600 dark:text-rose-400',
    badge: 'border border-rose-500/40 bg-rose-500/15 text-rose-700 dark:text-rose-300',
    text: 'text-rose-700 dark:text-rose-300',
    dot: 'bg-rose-600',
    border: 'border-l-rose-600',
  },
  urgent: {
    card: 'border-orange-500/40 bg-orange-500/5 dark:border-orange-500/30',
    icon: 'bg-orange-500/15 text-orange-600 dark:text-orange-400',
    badge: 'border border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300',
    text: 'text-orange-700 dark:text-orange-300',
    dot: 'bg-orange-500',
    border: 'border-l-orange-500',
  },
  warning: {
    card: 'border-amber-500/40 bg-amber-500/5 dark:border-amber-500/30',
    icon: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
    badge: 'border border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
    text: 'text-amber-700 dark:text-amber-300',
    dot: 'bg-amber-500',
    border: 'border-l-amber-500',
  },
  info: {
    card: 'border-slate-200 dark:border-slate-800',
    icon: 'bg-slate-500/10 text-slate-500',
    badge: 'border border-slate-500/30 bg-slate-500/10 text-slate-600 dark:text-slate-300',
    text: 'text-slate-700 dark:text-slate-200',
    dot: 'bg-slate-400',
    border: 'border-l-slate-400',
  },
}

function normalizeTone(value: unknown): string {
  const tone = String(value || '').trim().toLowerCase()
  return toneStyles[tone] ? tone : 'info'
}

function displayValue(value: unknown, fallback = '--'): string {
  if (value === null || value === undefined || value === '') return fallback
  return String(value)
}

/**
 * Relative-time label for a notification timestamp.
 *
 * Exported for regression testing. Routes through the shared `parseTimestampMs`
 * so epoch-seconds, epoch-ms, numeric strings, and ISO strings all parse. The
 * previous hand-rolled `Date.parse` could not parse a float epoch-seconds string
 * ("1780634112.7714157") and fell back to RETURNING THE RAW VALUE — which then
 * rendered verbatim as a broken-looking number in the panel header and rows.
 * Unparseable / missing now collapses to the '--' fallback instead.
 */
export function formatRelativeTime(value?: string | number | null): string {
  const ts = parseTimestampMs(value)
  if (ts == null) return NOTIFICATION_FALLBACKS.emptyTimestamp
  const diffSec = Math.floor((Date.now() - ts) / 1000)
  if (diffSec < 5) return 'just now'
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  return `${Math.floor(diffHr / 24)}d ago`
}

function NotificationEmptyState({ message }: { message: string }) {
  return <EmptyState message={message} />
}

export function NotificationFeed({
  notifications,
  wsConnected,
  onClearAll,
}: {
  notifications: Notification[]
  wsConnected: boolean
  onClearAll?: () => void
}) {
  // Only show notifications from the last hour so the feed reads live, not
  // stale (see NOTIFICATION_LIVE_WINDOW_MS). The store still holds the rest.
  const cutoffMs = Date.now() - NOTIFICATION_LIVE_WINDOW_MS
  const liveNotifications = notifications.filter((n) => isLiveNotification(n, cutoffMs))
  const lastTimestamp = liveNotifications[0]?.timestamp ?? null

  return (
    <div className={cardClass}>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell className="h-4 w-4 text-slate-500" />
          <p className={sectionTitleClass}>Notifications</p>
          {liveNotifications.length > 0 && (
            <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-slate-200 px-1.5 text-[10px] font-bold tabular-nums text-slate-600 dark:bg-slate-700 dark:text-slate-300">
              {liveNotifications.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {lastTimestamp && (
            <p className={mutedClass}>{formatRelativeTime(lastTimestamp)}</p>
          )}
          {onClearAll && liveNotifications.length > 0 && (
            <button
              onClick={onClearAll}
              className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200"
              aria-label="Clear all notifications"
            >
              <X className="h-3 w-3" />
              Clear
            </button>
          )}
        </div>
      </div>

      {liveNotifications.length === 0 ? (
        <NotificationEmptyState
          message={
            !wsConnected
              ? 'Stream disconnected'
              : notifications.length > 0
                ? 'No notifications in the last hour'
                : 'No notifications yet'
          }
        />
      ) : (
        <div className="max-h-[22rem] space-y-2 overflow-y-auto pr-0.5">
          {groupNotifications(liveNotifications).map(({ latest: notification, count }) => {
            const display = notification.display
            const tone = normalizeTone(display?.tone || notification.severity)
            const style = toneStyles[tone]
            const Icon = iconByName[display?.icon || NOTIFICATION_FALLBACKS.icon] || BellRing
            const title = displayValue(display?.title || notification.title || notification.notification_type, 'Notification')
            const subtitle = displayValue(display?.subtitle || notification.message, 'No message')
            const badges = Array.isArray(display?.badges) ? display.badges : []
            const facts = Array.isArray(display?.facts) ? display.facts : []
            const meta = Array.isArray(display?.meta) ? display.meta : []

            return (
              <article
                key={notification.id}
                className={cn(
                  'rounded-lg border-l-[3px] border border-l-transparent px-3 py-2.5 transition-all duration-200',
                  style.card,
                  style.border,
                )}
              >
                <div className="flex items-start gap-2.5">
                  <span className={cn('mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md', style.icon)}>
                    <Icon className="h-3.5 w-3.5" />
                  </span>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {badges.map((badge, index) => {
                        const badgeTone = normalizeTone(badge.tone || tone)
                        return (
                          <span
                            key={`${displayValue(badge.label)}-${index}`}
                            className={cn('rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide', toneStyles[badgeTone].badge)}
                          >
                            {displayValue(badge.label)}
                          </span>
                        )
                      })}
                      <h3 className="min-w-0 flex-1 truncate text-sm font-semibold leading-tight text-slate-900 dark:text-slate-100">{title}</h3>
                      {count > 1 && (
                        <span className="shrink-0 rounded-full bg-slate-200 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-slate-500 dark:bg-slate-700 dark:text-slate-400">
                          ×{count}
                        </span>
                      )}
                      <time className={cn(mutedClass, 'shrink-0 tabular-nums')} title={notification.timestamp ?? undefined}>
                        {formatRelativeTime(notification.timestamp)}
                      </time>
                    </div>

                    <p className="mt-0.5 text-xs leading-relaxed text-slate-600 dark:text-slate-400">{subtitle}</p>

                    {facts.length > 0 && (
                      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 rounded-md border border-slate-100 bg-slate-50/60 p-2 dark:border-slate-800 dark:bg-slate-900/60 sm:grid-cols-4">
                        {facts.map((fact, index) => {
                          const factTone = normalizeTone(fact.tone)
                          return (
                            <div key={`${displayValue(fact.label)}-${index}`} className="min-w-0">
                              <dt className={mutedClass}>{displayValue(fact.label)}</dt>
                              <dd
                                className={cn(
                                  'truncate text-xs font-mono font-semibold tabular-nums text-slate-900 dark:text-slate-100',
                                  fact.tone ? toneStyles[factTone].text : '',
                                )}
                              >
                                {displayValue(fact.value)}
                              </dd>
                            </div>
                          )
                        })}
                      </dl>
                    )}

                    {meta.length > 0 && (
                      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                        {meta.map((item, index) => (
                          <span key={`${displayValue(item.label)}-${index}`} className={mutedClass}>
                            <span className="font-medium">{displayValue(item.label)}</span>: {displayValue(item.value)}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </div>
  )
}
