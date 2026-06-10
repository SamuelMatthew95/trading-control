import { describe, it, expect } from 'vitest'
import {
  pnlColorClass,
  confColorClass,
  actionBadgeClass,
  activityDotClass,
  activityLabel,
  tradeFeedEmptyLabel,
  winRateFromFeed,
  systemStatusBadgeClass,
  agentStatusDotClass,
  apiHealthBadgeClass,
  agentTierFromStatus,
  proposalStatusClass,
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
  it('returns the success token for BUY', () => {
    expect(actionBadgeClass('BUY')).toContain('success')
  })
  it('returns the danger token for SELL', () => {
    expect(actionBadgeClass('SELL')).toContain('danger')
  })
  it('returns the muted token for HOLD', () => {
    expect(actionBadgeClass('HOLD')).toContain('muted')
  })
  it('returns the muted token for empty string', () => {
    expect(actionBadgeClass('')).toContain('muted')
  })
})

describe('activityDotClass', () => {
  it('includes animate-pulse and the success token for live', () => {
    const cls = activityDotClass('live')
    expect(cls).toContain('animate-pulse')
    expect(cls).toContain('bg-success')
  })
  it('returns the warning token for waiting', () => {
    expect(activityDotClass('waiting')).toBe('bg-warning')
  })
  it('returns the muted token for offline', () => {
    expect(activityDotClass('offline')).toBe('bg-muted-foreground')
  })
  it('returns the muted token for any unrecognised value', () => {
    expect(activityDotClass('unknown')).toBe('bg-muted-foreground')
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

describe('systemStatusBadgeClass', () => {
  it('returns the success token for trading', () => {
    expect(systemStatusBadgeClass('trading')).toContain('success')
  })
  it('returns the warning token for booting', () => {
    expect(systemStatusBadgeClass('booting')).toContain('warning')
  })
  it('returns the danger token for error', () => {
    expect(systemStatusBadgeClass('error')).toContain('danger')
  })
  it('returns the muted token for unknown status', () => {
    expect(systemStatusBadgeClass('offline')).toContain('muted')
  })
  it('returns the muted token for empty string', () => {
    expect(systemStatusBadgeClass('')).toContain('muted')
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
  it('returns the success token for Live', () => {
    expect(agentStatusDotClass('Live')).toBe('bg-success')
  })
  it('returns the warning token for Stale', () => {
    expect(agentStatusDotClass('Stale')).toBe('bg-warning')
  })
  it('returns the danger token for Error', () => {
    expect(agentStatusDotClass('Error')).toBe('bg-danger')
  })
  it('returns the muted token for Idle and unknown statuses', () => {
    expect(agentStatusDotClass('Idle')).toBe('bg-muted-foreground')
    expect(agentStatusDotClass('unknown')).toBe('bg-muted-foreground')
  })
})

describe('apiHealthBadgeClass', () => {
  it('returns the success token for ok', () => {
    expect(apiHealthBadgeClass('ok')).toContain('success')
  })
  it('returns the danger token for error', () => {
    expect(apiHealthBadgeClass('error')).toContain('danger')
  })
  it('returns the muted token for unknown values', () => {
    expect(apiHealthBadgeClass('pending')).toContain('muted')
    expect(apiHealthBadgeClass('')).toContain('muted')
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

describe('proposalStatusClass', () => {
  it('returns the success token for approved', () => {
    expect(proposalStatusClass('approved')).toContain('success')
  })
  it('returns the danger token for rejected', () => {
    expect(proposalStatusClass('rejected')).toContain('danger')
  })
  it('returns the warning token for pending / null / unknown', () => {
    expect(proposalStatusClass('pending')).toContain('warning')
    expect(proposalStatusClass(null)).toContain('warning')
    expect(proposalStatusClass('draft')).toContain('warning')
  })
})
