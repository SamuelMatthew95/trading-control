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
import {
  CHIP_BASE_BOLD,
  ICON_SM,
  NOTIFICATION_CARD,
  NOTIFICATION_FACT_VALUE,
  NOTIFICATION_FACTS_GRID,
  NOTIFICATION_ICON_BOX,
  ROW_WRAP,
  SCROLL_LIST_TIGHT,
  PRIMARY_TEXT,
  SECONDARY_TEXT,
} from '@/lib/styles'
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
        <div className={SCROLL_LIST_TIGHT}>
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
    <article className={cn(NOTIFICATION_CARD, cardTone.card)}>
      <div className="flex items-start gap-3">
        <span className={cn(NOTIFICATION_ICON_BOX, cardTone.soft)}>
          <Icon className={ICON_SM} />
        </span>

        <div className="min-w-0 flex-1">
          <div className={ROW_WRAP}>
            {badges.map((badge, index) => {
              const badgeTone = resolveTone(badge.tone || tone)
              return (
                <span
                  key={`${displayValue(badge.label)}-${index}`}
                  className={cn(CHIP_BASE_BOLD, TONE_CLASSES[badgeTone].chip)}
                >
                  {displayValue(badge.label)}
                </span>
              )
            })}
            <h3 className={cn('min-w-0 flex-1 truncate text-sm font-semibold', PRIMARY_TEXT)}>
              {title}
            </h3>
            <span className={cn(UI_TEXT.muted, 'shrink-0')}>
              {formatTimestamp(notification.timestamp)}
            </span>
          </div>

          <p className={cn('mt-1 text-sm', SECONDARY_TEXT)}>{subtitle}</p>

          {facts.length > 0 ? (
            <dl className={NOTIFICATION_FACTS_GRID}>
              {facts.map((fact, index) => {
                const factTone = resolveTone(fact.tone)
                const factHasTone = Boolean(fact.tone)
                return (
                  <div key={`${displayValue(fact.label)}-${index}`} className="min-w-0">
                    <dt className={UI_TEXT.muted}>{displayValue(fact.label)}</dt>
                    <dd
                      className={cn(
                        NOTIFICATION_FACT_VALUE,
                        factHasTone ? TONE_CLASSES[factTone].text : PRIMARY_TEXT,
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
            <div className={cn('mt-3', ROW_WRAP)}>
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
