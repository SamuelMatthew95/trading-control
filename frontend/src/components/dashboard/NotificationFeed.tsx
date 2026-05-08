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
import { TONE_CLASSES, type Tone } from '@/lib/state'
import { TerminalCard, SectionHeader, EmptyState } from '@/components/terminal'
import { UI_TEXT } from '@/lib/constants/ui'
import type { Notification } from '@/stores/useCodexStore'
import { NOTIFICATION_FALLBACKS } from '@/constants/notifications'

const ICON_BY_NAME: Record<string, ComponentType<{ className?: string }>> = {
  'arrow-down-right': ArrowDownRight,
  'arrow-up-right': ArrowUpRight,
  alert: AlertCircle,
  bell: BellRing,
  info: Info,
  warning: AlertTriangle,
}

/**
 * Map every legacy notification "tone" string the backend may emit to a
 * canonical Tone. Color now lives entirely in TONE_CLASSES — there is no
 * tone-specific Tailwind dictionary in this file anymore.
 */
const TONE_MAP: Record<string, Tone> = {
  buy: 'pos',
  gain: 'pos',
  sell: 'neg',
  loss: 'neg',
  critical: 'neg',
  urgent: 'warn',
  warning: 'warn',
  info: 'info',
}

function resolveTone(value: unknown): Tone {
  const key = String(value || '')
    .trim()
    .toLowerCase()
  return TONE_MAP[key] ?? 'info'
}

function displayValue(value: unknown, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback
  return String(value)
}

function formatTimestamp(value?: string | null): string {
  if (!value) return NOTIFICATION_FALLBACKS.emptyTimestamp
  return value
}

interface NotificationFeedProps {
  notifications: Notification[]
  wsConnected: boolean
}

export function NotificationFeed({ notifications, wsConnected }: NotificationFeedProps) {
  const lastTimestamp = notifications[0]?.timestamp ?? null

  return (
    <TerminalCard>
      <SectionHeader
        title="Notifications"
        icon={Bell}
        right={
          <>
            <p className={UI_TEXT.muted}>{notifications.length} total</p>
            {lastTimestamp ? (
              <p className={UI_TEXT.muted}>Last: {formatTimestamp(lastTimestamp)}</p>
            ) : null}
          </>
        }
      />

      {notifications.length === 0 ? (
        <EmptyState message={wsConnected ? 'No notifications yet' : 'Stream disconnected'} />
      ) : (
        <div className="max-h-72 space-y-2 overflow-y-auto">
          {notifications.map((notification) => (
            <NotificationRow key={notification.id} notification={notification} />
          ))}
        </div>
      )}
    </TerminalCard>
  )
}

function NotificationRow({ notification }: { notification: Notification }) {
  const display = notification.display
  const tone = resolveTone(display?.tone || notification.severity)
  const Icon = ICON_BY_NAME[display?.icon || NOTIFICATION_FALLBACKS.icon] ?? BellRing
  const title = displayValue(
    display?.title || notification.title || notification.notification_type,
    'Notification',
  )
  const subtitle = displayValue(display?.subtitle || notification.message, 'No message')
  const badges = Array.isArray(display?.badges) ? display.badges : []
  const facts = Array.isArray(display?.facts) ? display.facts : []
  const meta = Array.isArray(display?.meta) ? display.meta : []
  const cardTone = TONE_CLASSES[tone]

  return (
    <article className={cn('rounded-[6px] border px-3 py-3', cardTone.card)}>
      <div className="flex items-start gap-3">
        <span
          className={cn(
            'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-[6px]',
            cardTone.soft,
          )}
        >
          <Icon className="h-4 w-4" />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {badges.map((badge, index) => {
              const badgeTone = resolveTone(badge.tone || tone)
              return (
                <span
                  key={`${displayValue(badge.label)}-${index}`}
                  className={cn(
                    'rounded-[4px] px-2 py-0.5 text-xs font-bold uppercase',
                    TONE_CLASSES[badgeTone].chip,
                  )}
                >
                  {displayValue(badge.label)}
                </span>
              )
            })}
            <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
              {title}
            </h3>
            <span className={cn(UI_TEXT.muted, 'shrink-0')}>
              {formatTimestamp(notification.timestamp)}
            </span>
          </div>

          <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">{subtitle}</p>

          {facts.length > 0 ? (
            <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-4">
              {facts.map((fact, index) => {
                const factTone = resolveTone(fact.tone)
                const factHasTone = Boolean(fact.tone)
                return (
                  <div key={`${displayValue(fact.label)}-${index}`} className="min-w-0">
                    <dt className={UI_TEXT.muted}>{displayValue(fact.label)}</dt>
                    <dd
                      className={cn(
                        'truncate text-xs font-mono font-semibold tabular-nums',
                        factHasTone ? TONE_CLASSES[factTone].text : 'text-slate-900 dark:text-slate-100',
                      )}
                    >
                      {displayValue(fact.value)}
                    </dd>
                  </div>
                )
              })}
            </dl>
          ) : null}

          {meta.length > 0 ? (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {meta.map((item, index) => (
                <span key={`${displayValue(item.label)}-${index}`} className={UI_TEXT.muted}>
                  {displayValue(item.label)}: {displayValue(item.value)}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </article>
  )
}
