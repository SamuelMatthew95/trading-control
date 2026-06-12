'use client'

import type { ComponentType } from 'react'
import { EmptyState } from '@/components/ui/empty-state'
import { Button } from '@/components/ui/button'
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
import { cardClass, mutedClass, sectionTitleClass } from '@/lib/dashboard-styles'
import { formatTimeAgo, parseTimestampMs } from '@/lib/formatters'
import type { Notification } from '@/stores/useDashboardStore'
import { NOTIFICATION_FALLBACKS } from '@/constants/notifications'
import { NO_DATA, UI_COPY } from '@/constants/copy'
import { groupNotifications } from '@/lib/notification-grouping'
import { TraceButton } from '@/components/dashboard/TraceButton'

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

interface NotificationToneStyle {
  card: string
  icon: string
  badge: string
  text: string
  dot: string
  border: string
}

/**
 * Notification style recipes built on the semantic design tokens (class
 * strings stay static literals so Tailwind's JIT can see them). The "strong"
 * variants raise fill/border alpha one step so the severity ladder stays
 * visually ranked (warning < urgent < critical) without leaving the token
 * palette — light/dark parity comes from the tokens themselves.
 */
const SUCCESS_STYLE: NotificationToneStyle = {
  card: 'border-success/40 bg-success/5',
  icon: 'bg-success/15 text-success',
  badge: 'border border-success/30 bg-success/10 text-success',
  text: 'text-success',
  dot: 'bg-success',
  border: 'border-l-success',
}

const DANGER_STYLE: NotificationToneStyle = {
  card: 'border-danger/40 bg-danger/5',
  icon: 'bg-danger/15 text-danger',
  badge: 'border border-danger/30 bg-danger/10 text-danger',
  text: 'text-danger',
  dot: 'bg-danger',
  border: 'border-l-danger',
}

const DANGER_STRONG_STYLE: NotificationToneStyle = {
  card: 'border-danger/50 bg-danger/15',
  icon: 'bg-danger/15 text-danger',
  badge: 'border border-danger/40 bg-danger/10 text-danger',
  text: 'text-danger',
  dot: 'bg-danger',
  border: 'border-l-danger',
}

const WARNING_STYLE: NotificationToneStyle = {
  card: 'border-warning/40 bg-warning/5',
  icon: 'bg-warning/15 text-warning',
  badge: 'border border-warning/30 bg-warning/10 text-warning',
  text: 'text-warning',
  dot: 'bg-warning',
  border: 'border-l-warning',
}

const WARNING_STRONG_STYLE: NotificationToneStyle = {
  card: 'border-warning/50 bg-warning/15',
  icon: 'bg-warning/15 text-warning',
  badge: 'border border-warning/40 bg-warning/10 text-warning',
  text: 'text-warning',
  dot: 'bg-warning',
  border: 'border-l-warning',
}

const toneStyles: Record<string, NotificationToneStyle> = {
  buy: SUCCESS_STYLE,
  gain: SUCCESS_STYLE,
  sell: DANGER_STYLE,
  loss: DANGER_STYLE,
  critical: DANGER_STRONG_STYLE,
  urgent: WARNING_STRONG_STYLE,
  warning: WARNING_STYLE,
  info: {
    card: '',
    icon: 'bg-muted-foreground/10 text-muted-foreground',
    badge: 'border border-muted-foreground/30 bg-muted-foreground/10 text-foreground/70',
    text: 'text-foreground/80',
    dot: 'bg-muted-foreground',
    border: 'border-l-muted-foreground',
  },
}

function normalizeTone(value: unknown): string {
  const tone = String(value || '').trim().toLowerCase()
  return toneStyles[tone] ? tone : 'info'
}

function displayValue(value: unknown, fallback = NO_DATA): string {
  if (value === null || value === undefined || value === '') return fallback
  return String(value)
}

export function NotificationFeed({
  notifications,
  wsConnected,
  onClearAll,
  onSelectTrace,
}: {
  notifications: Notification[]
  wsConnected: boolean
  onClearAll?: () => void
  /** Drill-down: open the full trace for a notification. Optional — the trace
   *  button only renders when wired AND the notification carries a trace_id. */
  onSelectTrace?: (traceId: string) => void
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
          <Bell className="h-4 w-4 text-muted-foreground" aria-hidden />
          <p className={sectionTitleClass}>{UI_COPY.notifications.title}</p>
          {liveNotifications.length > 0 && (
            <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-muted px-1.5 text-3xs font-bold tabular-nums text-foreground/70">
              {liveNotifications.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {lastTimestamp && <p className={mutedClass}>{formatTimeAgo(lastTimestamp)}</p>}
          {onClearAll && liveNotifications.length > 0 && (
            <Button
              variant="ghost"
              size="xs"
              onClick={onClearAll}
              aria-label={UI_COPY.notifications.clearAria}
            >
              <X className="h-3 w-3" aria-hidden />
              {UI_COPY.actions.clear}
            </Button>
          )}
        </div>
      </div>

      {liveNotifications.length === 0 ? (
        <EmptyState
          message={
            !wsConnected
              ? UI_COPY.notifications.streamDisconnected
              : notifications.length > 0
                ? UI_COPY.notifications.noneInWindow
                : UI_COPY.notifications.noneYet
          }
        />
      ) : (
        <div className="max-h-[22rem] space-y-2 overflow-y-auto pr-0.5">
          {groupNotifications(liveNotifications).map(({ latest: notification, count }) => {
            const display = notification.display
            const tone = normalizeTone(display?.tone || notification.severity)
            const style = toneStyles[tone]
            const Icon = iconByName[display?.icon || NOTIFICATION_FALLBACKS.icon] || BellRing
            const title = displayValue(
              display?.title || notification.title || notification.notification_type,
              UI_COPY.notifications.fallbackTitle,
            )
            const subtitle = displayValue(
              display?.subtitle || notification.message,
              UI_COPY.notifications.fallbackMessage,
            )
            const badges = Array.isArray(display?.badges) ? display.badges : []
            const facts = Array.isArray(display?.facts) ? display.facts : []
            const meta = Array.isArray(display?.meta) ? display.meta : []

            return (
              <article
                key={notification.id}
                className={cn(
                  'rounded-lg border border-l-[3px] border-l-transparent px-3 py-2.5 transition-all duration-200',
                  style.card,
                  style.border,
                )}
              >
                <div className="flex items-start gap-2.5">
                  <span className={cn('mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md', style.icon)}>
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                  </span>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {badges.map((badge, index) => {
                        const badgeTone = normalizeTone(badge.tone || tone)
                        return (
                          <span
                            key={`${displayValue(badge.label)}-${index}`}
                            className={cn('rounded px-1.5 py-0.5 text-3xs font-semibold uppercase tracking-caps', toneStyles[badgeTone].badge)}
                          >
                            {displayValue(badge.label)}
                          </span>
                        )
                      })}
                      <h3 className="min-w-0 flex-1 truncate text-sm font-semibold leading-tight text-foreground">{title}</h3>
                      {count > 1 && (
                        <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-3xs font-bold tabular-nums text-muted-foreground">
                          ×{count}
                        </span>
                      )}
                      <time className={cn(mutedClass, 'shrink-0 tabular-nums')} title={notification.timestamp ?? undefined}>
                        {formatTimeAgo(notification.timestamp)}
                      </time>
                      {notification.trace_id && onSelectTrace && (
                        <TraceButton onClick={() => onSelectTrace(String(notification.trace_id))} />
                      )}
                    </div>

                    <p className="mt-0.5 text-xs leading-relaxed text-foreground/70">{subtitle}</p>

                    {facts.length > 0 && (
                      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 rounded-md border bg-muted/40 p-2 sm:grid-cols-4">
                        {facts.map((fact, index) => {
                          const factTone = normalizeTone(fact.tone)
                          return (
                            <div key={`${displayValue(fact.label)}-${index}`} className="min-w-0">
                              <dt className={mutedClass}>{displayValue(fact.label)}</dt>
                              <dd
                                className={cn(
                                  'truncate text-xs font-mono font-semibold tabular-nums text-foreground',
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
