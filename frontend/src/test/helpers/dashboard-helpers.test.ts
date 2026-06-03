import { describe, it, expect } from 'vitest'
import {
  pnlColorClass,
  tradeSideClass,
  strategyStatusClass,
  confColorClass,
  actionBadgeClass,
  positionSideBadgeClass,
  activityDotClass,
  activityLabel,
  tradeFeedEmptyLabel,
  winRateFromFeed,
  agentCardBorderClass,
  agentCardDotClass,
  agentCardTextClass,
  streamEventBadgeClass,
  systemStatusBadgeClass,
  agentStatusDotClass,
  pipelineStatusTextClass,
  apiHealthBadgeClass,
  priceChangeTextClass,
  agentTierFromStatus,
  performancePnlColorClass,
} from '@/lib/dashboard-helpers'
import { sentimentOf, sentimentTextClass, SENTIMENT_EPSILON } from '@/lib/design/sentiment'

describe('sentiment (single source of truth for directional colour)', () => {
  it('maps clearly positive / negative values', () => {
    expect(sentimentOf(5)).toBe('positive')
    expect(sentimentOf(-5)).toBe('negative')
  })
  it('treats within-dead-band, zero, null and NaN as neutral', () => {
    expect(sentimentOf(SENTIMENT_EPSILON / 2)).toBe('neutral')
    expect(sentimentOf(0)).toBe('neutral')
    expect(sentimentOf(null)).toBe('neutral')
    expect(sentimentOf(Number.NaN)).toBe('neutral')
  })
  it('resolves to the semantic success/danger/muted Tone tokens', () => {
    expect(sentimentTextClass(5)).toBe('text-success')
    expect(sentimentTextClass(-5)).toBe('text-danger')
    expect(sentimentTextClass(0)).toBe('text-muted-foreground')
  })
  it('shares its palette with pnlColorClass — proves no duplicate literal', () => {
    expect(pnlColorClass(100)).toBe(sentimentTextClass(100))
  })
})

describe('pnlColorClass', () => {
  it('returns the success token for positive values', () => {
    expect(pnlColorClass(100)).toBe('text-success')
  })
  it('returns the danger token for negative values', () => {
    expect(pnlColorClass(-1)).toBe('text-danger')
  })
  it('returns the success token for zero (not a loss)', () => {
    expect(pnlColorClass(0)).toBe('text-success')
  })
})

describe('tradeSideClass', () => {
  it('returns the success token for buy', () => {
    expect(tradeSideClass('buy')).toBe('text-success')
  })
  it('returns the danger token for sell', () => {
    expect(tradeSideClass('sell')).toBe('text-danger')
  })
  it('returns the danger token for null (unknown treated as sell)', () => {
    expect(tradeSideClass(null)).toBe('text-danger')
  })
  it('returns the danger token for unrecognised side', () => {
    expect(tradeSideClass('short')).toBe('text-danger')
  })
})

describe('strategyStatusClass', () => {
  it('returns emerald for approved', () => {
    expect(strategyStatusClass('approved')).toContain('emerald')
  })
  it('returns rose for rejected', () => {
    expect(strategyStatusClass('rejected')).toContain('rose')
  })
  it('returns amber for pending', () => {
    expect(strategyStatusClass('pending')).toContain('amber')
  })
  it('returns amber for null (treated as pending)', () => {
    expect(strategyStatusClass(null)).toContain('amber')
  })
  it('returns amber for unknown status', () => {
    expect(strategyStatusClass('draft')).toContain('amber')
  })
})

describe('confColorClass', () => {
  it('returns the muted token for null', () => {
    expect(confColorClass(null)).toBe('text-muted-foreground')
  })
  it('returns the success token for confidence > 0.8', () => {
    expect(confColorClass(0.9)).toBe('text-success')
    expect(confColorClass(0.81)).toBe('text-success')
  })
  it('returns the warning token for confidence in [0.5, 0.8]', () => {
    expect(confColorClass(0.5)).toBe('text-warning')
    expect(confColorClass(0.8)).toBe('text-warning')
    expect(confColorClass(0.65)).toBe('text-warning')
  })
  it('returns the muted token for confidence below 0.5', () => {
    expect(confColorClass(0.49)).toBe('text-muted-foreground')
    expect(confColorClass(0)).toBe('text-muted-foreground')
  })
})

describe('actionBadgeClass', () => {
  it('returns emerald for BUY', () => {
    expect(actionBadgeClass('BUY')).toContain('emerald')
  })
  it('returns rose for SELL', () => {
    expect(actionBadgeClass('SELL')).toContain('rose')
  })
  it('returns slate for HOLD', () => {
    expect(actionBadgeClass('HOLD')).toContain('slate')
  })
  it('returns slate for empty string', () => {
    expect(actionBadgeClass('')).toContain('slate')
  })
})

describe('positionSideBadgeClass', () => {
  it('returns emerald for LONG', () => {
    expect(positionSideBadgeClass('LONG')).toContain('emerald')
  })
  it('returns rose for SHORT', () => {
    expect(positionSideBadgeClass('SHORT')).toContain('rose')
  })
  it('returns slate for empty string', () => {
    expect(positionSideBadgeClass('')).toContain('slate')
  })
  it('returns slate for unrecognised value', () => {
    expect(positionSideBadgeClass('FLAT')).toContain('slate')
  })
})

describe('activityDotClass', () => {
  it('includes animate-pulse and emerald for live', () => {
    const cls = activityDotClass('live')
    expect(cls).toContain('animate-pulse')
    expect(cls).toContain('emerald')
  })
  it('returns amber for waiting', () => {
    expect(activityDotClass('waiting')).toContain('amber')
  })
  it('returns slate for offline', () => {
    expect(activityDotClass('offline')).toContain('slate')
  })
  it('returns slate for any unrecognised value', () => {
    expect(activityDotClass('unknown')).toContain('slate')
  })
})

describe('activityLabel', () => {
  it('returns LIVE for live', () => {
    expect(activityLabel('live')).toBe('LIVE')
  })
  it('returns WAITING for waiting', () => {
    expect(activityLabel('waiting')).toBe('WAITING')
  })
  it('returns OFFLINE for offline', () => {
    expect(activityLabel('offline')).toBe('OFFLINE')
  })
  it('returns OFFLINE for any unrecognised value', () => {
    expect(activityLabel('disconnected')).toBe('OFFLINE')
  })
})

describe('tradeFeedEmptyLabel', () => {
  it('returns DB message for db_degraded', () => {
    expect(tradeFeedEmptyLabel('db_degraded')).toMatch(/DB unavailable/)
  })
  it('returns orders message for no_orders_executed', () => {
    expect(tradeFeedEmptyLabel('no_orders_executed')).toMatch(/No orders executed/)
  })
  it('returns lifecycle message for lifecycle_not_persisted', () => {
    expect(tradeFeedEmptyLabel('lifecycle_not_persisted')).toMatch(/lifecycle/)
  })
  it('returns pipeline message for no_executable_intents', () => {
    expect(tradeFeedEmptyLabel('no_executable_intents')).toMatch(/Pipeline active/)
  })
  it('returns default fallback for null', () => {
    expect(tradeFeedEmptyLabel(null)).toMatch(/No fills yet/)
  })
  it('returns default fallback for unrecognised reason', () => {
    expect(tradeFeedEmptyLabel('some_other_reason')).toMatch(/No fills yet/)
  })
})

describe('agentCardBorderClass', () => {
  it('returns emerald for Live', () => {
    expect(agentCardBorderClass('Live')).toContain('emerald')
  })
  it('returns rose for Error', () => {
    expect(agentCardBorderClass('Error')).toContain('rose')
  })
  it('returns slate for Stale', () => {
    expect(agentCardBorderClass('Stale')).toContain('slate')
  })
  it('returns slate for Idle', () => {
    expect(agentCardBorderClass('Idle')).toContain('slate')
  })
  it('returns slate for unknown status', () => {
    expect(agentCardBorderClass('unknown')).toContain('slate')
  })
})

describe('agentCardDotClass', () => {
  it('includes animate-pulse and emerald for Live', () => {
    const cls = agentCardDotClass('Live')
    expect(cls).toContain('animate-pulse')
    expect(cls).toContain('emerald')
  })
  it('returns amber for Stale', () => {
    expect(agentCardDotClass('Stale')).toContain('amber')
  })
  it('returns rose for Error', () => {
    expect(agentCardDotClass('Error')).toContain('rose')
  })
  it('returns slate for Idle', () => {
    expect(agentCardDotClass('Idle')).toContain('slate')
  })
  it('returns slate for unknown status', () => {
    expect(agentCardDotClass('unknown')).toContain('slate')
  })
})

describe('agentCardTextClass', () => {
  it('returns the success token for Live', () => {
    expect(agentCardTextClass('Live')).toBe('text-success')
  })
  it('returns the warning token for Stale', () => {
    expect(agentCardTextClass('Stale')).toBe('text-warning')
  })
  it('returns the danger token for Error', () => {
    expect(agentCardTextClass('Error')).toBe('text-danger')
  })
  it('returns the muted token for Idle', () => {
    expect(agentCardTextClass('Idle')).toBe('text-muted-foreground')
  })
  it('returns the muted token for unknown status', () => {
    expect(agentCardTextClass('unknown')).toBe('text-muted-foreground')
  })
})

describe('streamEventBadgeClass', () => {
  it('returns emerald for market_ticks', () => {
    expect(streamEventBadgeClass('market_ticks')).toContain('emerald')
  })
  it('returns emerald for market_events', () => {
    expect(streamEventBadgeClass('market_events')).toContain('emerald')
  })
  it('returns sky for signals', () => {
    expect(streamEventBadgeClass('signals')).toContain('sky')
  })
  it('returns violet for decisions', () => {
    expect(streamEventBadgeClass('decisions')).toContain('violet')
  })
  it('returns amber for orders', () => {
    expect(streamEventBadgeClass('orders')).toContain('amber')
  })
  it('returns orange for executions', () => {
    expect(streamEventBadgeClass('executions')).toContain('orange')
  })
  it('returns rose for risk_alerts', () => {
    expect(streamEventBadgeClass('risk_alerts')).toContain('rose')
  })
  it('returns blue for notifications', () => {
    expect(streamEventBadgeClass('notifications')).toContain('blue')
  })
  it('returns indigo for system_metrics', () => {
    expect(streamEventBadgeClass('system_metrics')).toContain('indigo')
  })
  it('returns pink for graded_decisions', () => {
    expect(streamEventBadgeClass('graded_decisions')).toContain('pink')
  })
  it('returns slate for unknown stream', () => {
    expect(streamEventBadgeClass('mystery_stream')).toContain('slate')
  })
  it('returns slate for null', () => {
    expect(streamEventBadgeClass(null)).toContain('slate')
  })
  it('returns slate for undefined', () => {
    expect(streamEventBadgeClass(undefined)).toContain('slate')
  })
})

describe('systemStatusBadgeClass', () => {
  it('returns emerald for trading', () => {
    expect(systemStatusBadgeClass('trading')).toContain('emerald')
  })
  it('returns amber for booting', () => {
    expect(systemStatusBadgeClass('booting')).toContain('amber')
  })
  it('returns rose for error', () => {
    expect(systemStatusBadgeClass('error')).toContain('rose')
  })
  it('returns slate for unknown status', () => {
    expect(systemStatusBadgeClass('offline')).toContain('slate')
  })
  it('returns slate for empty string', () => {
    expect(systemStatusBadgeClass('')).toContain('slate')
  })
})

describe('winRateFromFeed', () => {
  it('returns null for empty feed', () => {
    expect(winRateFromFeed([])).toBeNull()
  })
  it('returns null when no entries have pnl', () => {
    expect(winRateFromFeed([{ pnl: null }, { pnl: undefined }])).toBeNull()
  })
  it('returns 100 when all trades are winning', () => {
    expect(winRateFromFeed([{ pnl: 10 }, { pnl: 5 }])).toBe(100)
  })
  it('returns 0 when all trades are losing', () => {
    expect(winRateFromFeed([{ pnl: -10 }, { pnl: -5 }])).toBe(0)
  })
  it('returns 50 for one win and one loss', () => {
    expect(winRateFromFeed([{ pnl: 10 }, { pnl: -5 }])).toBe(50)
  })
  it('ignores entries without pnl when computing rate', () => {
    // 1 win, 1 loss, 1 null — rate should be 50% from the 2 entries with pnl
    expect(winRateFromFeed([{ pnl: 10 }, { pnl: -5 }, { pnl: null }])).toBe(50)
  })
  it('treats pnl of 0 as a loss (not a win)', () => {
    // pnl > 0 check means exactly 0 is not counted as a win
    expect(winRateFromFeed([{ pnl: 0 }, { pnl: 10 }])).toBe(50)
  })
})

describe('agentStatusDotClass', () => {
  it('returns emerald for Live', () => {
    expect(agentStatusDotClass('Live')).toContain('emerald')
  })
  it('returns amber for Stale', () => {
    expect(agentStatusDotClass('Stale')).toContain('amber')
  })
  it('returns rose for Error', () => {
    expect(agentStatusDotClass('Error')).toContain('rose')
  })
  it('returns slate for Idle', () => {
    expect(agentStatusDotClass('Idle')).toContain('slate')
  })
  it('uses lighter shade than agentCardDotClass (bg-emerald-300 not 500)', () => {
    expect(agentStatusDotClass('Live')).toBe('bg-emerald-300')
  })
})

describe('pipelineStatusTextClass', () => {
  it('returns the success token for Healthy', () => {
    expect(pipelineStatusTextClass('Healthy')).toBe('text-success')
  })
  it('returns the warning token for Degraded', () => {
    expect(pipelineStatusTextClass('Degraded')).toBe('text-warning')
  })
  it('returns the danger token for Stalled or unknown', () => {
    expect(pipelineStatusTextClass('Stalled')).toBe('text-danger')
    expect(pipelineStatusTextClass('unknown')).toBe('text-danger')
  })
})

describe('apiHealthBadgeClass', () => {
  it('returns emerald for ok', () => {
    expect(apiHealthBadgeClass('ok')).toContain('emerald')
  })
  it('returns rose for error', () => {
    expect(apiHealthBadgeClass('error')).toContain('rose')
  })
  it('returns slate for unknown values', () => {
    expect(apiHealthBadgeClass('pending')).toContain('slate')
    expect(apiHealthBadgeClass('')).toContain('slate')
  })
})

describe('priceChangeTextClass', () => {
  it('returns the muted token when change is null', () => {
    expect(priceChangeTextClass(null, true)).toBe('text-muted-foreground')
  })
  it('returns the muted token when hasData is false', () => {
    expect(priceChangeTextClass(5, false)).toBe('text-muted-foreground')
  })
  it('returns the success token for positive change', () => {
    expect(priceChangeTextClass(1, true)).toBe('text-success')
  })
  it('returns the danger token for negative change', () => {
    expect(priceChangeTextClass(-1, true)).toBe('text-danger')
  })
  it('returns the muted token for zero change', () => {
    expect(priceChangeTextClass(0, true)).toBe('text-muted-foreground')
  })
})

describe('agentTierFromStatus', () => {
  it('returns active for Live', () => {
    expect(agentTierFromStatus('Live')).toBe('active')
  })
  it('returns inactive for Error', () => {
    expect(agentTierFromStatus('Error')).toBe('inactive')
  })
  it('returns challenger for Stale', () => {
    expect(agentTierFromStatus('Stale')).toBe('challenger')
  })
  it('returns challenger for Idle', () => {
    expect(agentTierFromStatus('Idle')).toBe('challenger')
  })
})

describe('performancePnlColorClass', () => {
  it('keeps the heading slate for null pnl', () => {
    expect(performancePnlColorClass(null)).toContain('slate')
  })
  it('returns the success token for positive pnl', () => {
    expect(performancePnlColorClass(100)).toBe('text-success')
  })
  it('returns the success token for zero pnl', () => {
    expect(performancePnlColorClass(0)).toBe('text-success')
  })
  it('returns the danger token for negative pnl', () => {
    expect(performancePnlColorClass(-1)).toBe('text-danger')
  })
})
