'use client'

import type { ComponentType } from 'react'
import {
  ArrowDownRight,
  ArrowUpRight,
  AlertCircle,
  AlertTriangle,
  Bell,
  BellRing,
  Info,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Notification } from '@/stores/useCodexStore'
import { NOTIFICATION_FALLBACKS } from '@/constants/notifications'

const cardClass =
  'rounded-lg border border-slate-200 bg-white p-4 transition-colors duration-150 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-600 sm:p-5'
const sectionTitleClass = 'text-xs font-semibold uppercase font-sans text-slate-500 dark:text-slate-400'
const mutedClass = 'text-xs font-sans text-slate-500 dark:text-slate-400'

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
  }
> = {
  buy: {
    card: 'border-emerald-500/40 bg-emerald-500/5 dark:border-emerald-500/30',
    icon: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
    badge: 'border border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
    text: 'text-emerald-700 dark:text-emerald-300',
    dot: 'bg-emerald-500',
  },
  sell: {
    card: 'border-rose-500/40 bg-rose-500/5 dark:border-rose-500/30',
    icon: 'bg-rose-500/10 text-rose-600 dark:text-rose-400',
    badge: 'border border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300',
    text: 'text-rose-700 dark:text-rose-300',
    dot: 'bg-rose-500',
  },
  gain: {
    card: 'border-emerald-500/40 bg-emerald-500/5 dark:border-emerald-500/30',
    icon: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
    badge: 'border border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
    text: 'text-emerald-700 dark:text-emerald-300',
    dot: 'bg-emerald-500',
  },
  loss: {
    card: 'border-rose-500/40 bg-rose-500/5 dark:border-rose-500/30',
    icon: 'bg-rose-500/10 text-rose-600 dark:text-rose-400',
    badge: 'border border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300',
    text: 'text-rose-700 dark:text-rose-300',
    dot: 'bg-rose-500',
  },
  critical: {
    card: 'border-rose-500/40 bg-rose-500/5 dark:border-rose-500/30',
    icon: 'bg-rose-500/10 text-rose-600 dark:text-rose-400',
    badge: 'border border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300',
    text: 'text-rose-700 dark:text-rose-300',
    dot: 'bg-rose-500',
  },
  urgent: {
    card: 'border-orange-500/40 bg-orange-500/5 dark:border-orange-500/30',
    icon: 'bg-orange-500/10 text-orange-600 dark:text-orange-400',
    badge: 'border border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300',
    text: 'text-orange-700 dark:text-orange-300',
    dot: 'bg-orange-500',
  },
  warning: {
    card: 'border-amber-500/40 bg-amber-500/5 dark:border-amber-500/30',
    icon: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
    badge: 'border border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
    text: 'text-amber-700 dark:text-amber-300',
    dot: 'bg-amber-500',
  },
  info: {
    card: 'border-slate-200 dark:border-slate-800',
    icon: 'bg-slate-500/10 text-slate-500',
    badge: 'border border-slate-500/30 bg-slate-500/10 text-slate-600 dark:text-slate-300',
    text: 'text-slate-700 dark:text-slate-200',
    dot: 'bg-slate-400',
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

function formatTimestamp(value?: string | null): string {
  if (!value) return NOTIFICATION_FALLBACKS.emptyTimestamp
  return value
}

function NotificationEmptyState({ message }: { message: string }) {
  return (
    <div className="flex h-28 items-center justify-center rounded-lg border border-dashed border-slate-200 text-sm text-slate-400 dark:border-slate-800">
      {message}
    </div>
  )
}

export function NotificationFeed({
  notifications,
  wsConnected,
}: {
  notifications: Notification[]
  wsConnected: boolean
}) {
  const lastTimestamp = notifications[0]?.timestamp ?? null

  return (
    <div className={cardClass}>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell className="h-4 w-4 text-slate-500" />
          <p className={sectionTitleClass}>Notifications</p>
        </div>
        <div className="flex items-center gap-3">
          <p className={mutedClass}>{notifications.length} total</p>
          {lastTimestamp && (
            <p className={mutedClass}>Last: {formatTimestamp(lastTimestamp)}</p>
          )}
        </div>
      </div>

      {notifications.length === 0 ? (
        <NotificationEmptyState message={wsConnected ? 'No notifications yet' : 'Stream disconnected'} />
      ) : (
        <div className="max-h-72 space-y-2 overflow-y-auto">
          {notifications.map((notification) => {
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
                className={cn('rounded-lg border px-3 py-3', style.card)}
              >
                <div className="flex items-start gap-3">
                  <span className={cn('mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md', style.icon)}>
                    <Icon className="h-4 w-4" />
                  </span>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      {badges.map((badge, index) => {
                        const badgeTone = normalizeTone(badge.tone || tone)
                        return (
                          <span
                            key={`${displayValue(badge.label)}-${index}`}
                            className={cn('rounded px-2 py-0.5 text-xs font-black uppercase', toneStyles[badgeTone].badge)}
                          >
                            {displayValue(badge.label)}
                          </span>
                        )
                      })}
                      <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
                      <span className={cn(mutedClass, 'shrink-0')}>{formatTimestamp(notification.timestamp)}</span>
                    </div>

                    <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">{subtitle}</p>

                    {facts.length > 0 && (
                      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-4">
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
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        {meta.map((item, index) => (
                          <span key={`${displayValue(item.label)}-${index}`} className={mutedClass}>
                            {displayValue(item.label)}: {displayValue(item.value)}
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
